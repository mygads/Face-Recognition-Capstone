from __future__ import annotations

import math
import os
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.request_rate_limit import EnrollmentOperator
from presensi_api.api.v1.schemas.common import PageResponse, Pagination
from presensi_api.api.v1.schemas.enrollment import (
    EnrollmentCaptureResultResponse,
    EnrollmentDuplicateWarning,
    EnrollmentStudentStatusResponse,
    FaceTemplateResponse,
    TemplateEnrollmentRequest,
    TemplateRevocationResponse,
)
from presensi_api.biometric_crypto import (
    BiometricCryptographyError,
    FaceTemplateKeyring,
    cosine_similarity,
    require_face_template_keyring,
)
from presensi_api.db.models import (
    AuditLog,
    ClassStudent,
    FaceTemplate,
    SchoolClass,
    Student,
)
from presensi_api.db.session import get_db_session
from presensi_api.enrollment_processing import (
    MAX_CAPTURE_BYTES,
    MAX_TOTAL_CAPTURE_BYTES,
    EnrollmentFrameResult,
    EnrollmentProcessor,
    get_enrollment_processor,
)
from presensi_api.runtime_configuration import configuration_values
from presensi_api.session_lifecycle import as_utc

router = APIRouter(tags=["enrollment", "templates"])
DbSession = Annotated[Session, Depends(get_db_session)]
EnrollmentStatus = Literal["not_enrolled", "enrolled", "needs_reenrollment"]
MIN_ACCEPTED_TEMPLATES = 3
MAX_STORED_TEMPLATES = 5
MAX_CAPTURES = 10
ALLOWED_IMAGE_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def configured_enrollment_processor(session: DbSession) -> EnrollmentProcessor:
    _, quality_settings, _ = configuration_values(session, "enrollment")
    return get_enrollment_processor(quality_settings or None)


@router.get(
    "/enrollments/class-status",
    response_model=list[EnrollmentStudentStatusResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List enrollment status for a class roster",
)
def list_class_enrollment_status(
    class_id: Annotated[UUID, Query()],
    session: DbSession,
    principal: EnrollmentOperator,
) -> list[EnrollmentStudentStatusResponse]:
    del principal
    school_class = session.get(SchoolClass, class_id)
    if school_class is None:
        raise ApiProblem(404, "class_not_found", "Kelas tidak ditemukan.")

    students = session.execute(
        select(Student.id, Student.student_number, Student.full_name)
        .join(ClassStudent, ClassStudent.student_id == Student.id)
        .where(ClassStudent.class_id == class_id, Student.is_active.is_(True))
        .order_by(Student.student_number, Student.id)
    ).all()
    student_ids = [student.id for student in students]
    template_rows = (
        session.execute(
            select(FaceTemplate.student_id, FaceTemplate.revoked_at).where(
                FaceTemplate.student_id.in_(student_ids)
            )
        ).all()
        if student_ids
        else []
    )
    statuses: dict[UUID, EnrollmentStatus] = {
        student_id: "not_enrolled" for student_id in student_ids
    }
    for student_id, revoked_at in template_rows:
        if revoked_at is None:
            statuses[student_id] = "enrolled"
        elif statuses[student_id] == "not_enrolled":
            statuses[student_id] = "needs_reenrollment"

    return [
        EnrollmentStudentStatusResponse(
            id=student.id,
            student_number=student.student_number,
            full_name=student.full_name,
            template_status=statuses[student.id],
        )
        for student in students
    ]


@router.post(
    "/enrollments",
    response_model=FaceTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Reject metadata-only enrollment requests",
    description="Templates can be created only by submitting multiple captures.",
)
def create_enrollment(
    request: TemplateEnrollmentRequest, principal: EnrollmentOperator
) -> FaceTemplateResponse:
    del request, principal
    raise ApiProblem(
        422,
        "captures_required",
        "Face templates must be created from multiple processed captures.",
    )


@router.post(
    "/enrollments/captures",
    response_model=EnrollmentCaptureResultResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Process multiple enrollment captures and store encrypted templates",
    description=(
        "The API rejects invalid, low-quality, or multi-face captures. It stores "
        "only encrypted embeddings and quality metadata; uploaded images are "
        "discarded after request processing."
    ),
)
async def submit_enrollment_captures(
    student_id: Annotated[UUID, Form()],
    captures: Annotated[list[UploadFile], File(min_length=3, max_length=MAX_CAPTURES)],
    principal: EnrollmentOperator,
    session: DbSession,
    processor: EnrollmentProcessor = Depends(configured_enrollment_processor),
) -> EnrollmentCaptureResultResponse:
    student = session.scalar(
        select(Student).where(Student.id == student_id).with_for_update()
    )
    if student is None or not student.is_active:
        raise ApiProblem(404, "student_not_found", "Siswa aktif tidak ditemukan.")

    uploaded_frames: list[bytes] = []
    total_bytes = 0
    for capture in captures:
        suffix = os.path.splitext(capture.filename or "")[1].lower()
        content_type = (capture.content_type or "").lower()
        if suffix not in ALLOWED_IMAGE_TYPES or (
            ALLOWED_IMAGE_TYPES[suffix] != content_type
        ):
            raise ApiProblem(
                415,
                "unsupported_capture_type",
                "Gunakan gambar JPEG, PNG, atau WebP dengan ekstensi yang sesuai.",
            )
        data = await capture.read(MAX_CAPTURE_BYTES + 1)
        if not data or len(data) > MAX_CAPTURE_BYTES:
            raise ApiProblem(
                413, "capture_too_large", "Ukuran tiap capture maksimal 3 MB."
            )
        total_bytes += len(data)
        if total_bytes > MAX_TOTAL_CAPTURE_BYTES:
            raise ApiProblem(
                413, "enrollment_upload_too_large", "Total capture melebihi 15 MB."
            )
        uploaded_frames.append(data)

    results: list[EnrollmentFrameResult] = []
    for data in uploaded_frames:
        try:
            result = processor.process(data, model_version="configured")
        except Exception as exc:
            raise ApiProblem(
                422,
                "capture_processing_failed",
                "Salah satu capture tidak dapat diproses.",
            ) from exc
        results.append(result)
    accepted = [result for result in results if result.accepted]
    rejected_count = len(results) - len(accepted)
    if len(accepted) < MIN_ACCEPTED_TEMPLATES:
        raise ApiProblem(
            422,
            "insufficient_quality_captures",
            "Minimal tiga capture harus lolos pemeriksaan kualitas dan deteksi wajah.",
        )
    model_pairs = {(result.model_name, result.model_version) for result in accepted}
    if len(model_pairs) != 1:
        raise ApiProblem(
            503,
            "enrollment_model_mismatch",
            "Model recognition berubah selama pemrosesan enrollment.",
        )
    model_name, model_version = next(iter(model_pairs))
    chosen = sorted(accepted, key=lambda item: item.quality_score, reverse=True)[
        :MAX_STORED_TEMPLATES
    ]
    if any(result.embedding is None for result in chosen):
        raise ApiProblem(
            503,
            "enrollment_embedding_missing",
            "Embedding hasil capture tidak lengkap.",
        )

    keyring = require_face_template_keyring()
    active_existing = session.scalars(
        select(FaceTemplate).where(
            FaceTemplate.student_id == student_id,
            FaceTemplate.model_name == model_name,
            FaceTemplate.model_version == model_version,
            FaceTemplate.revoked_at.is_(None),
        )
    ).all()
    if active_existing:
        raise ApiProblem(
            409,
            "templates_already_enrolled",
            "Template aktif sudah ada. Cabut enrollment saat ini sebelum re-enroll.",
        )

    duplicate_warnings = _find_duplicate_lookalikes(
        session,
        keyring,
        student_id=student_id,
        model_name=model_name,
        model_version=model_version,
        new_embeddings=tuple(
            result.embedding for result in chosen if result.embedding is not None
        ),
    )
    batch_id = uuid4()
    created: list[FaceTemplate] = []
    for result in chosen:
        assert result.embedding is not None
        template_id = uuid4()
        encrypted = keyring.encrypt(
            result.embedding,
            template_id=template_id,
            student_id=student_id,
            model_name=model_name,
            model_version=model_version,
        )
        template = FaceTemplate(
            id=template_id,
            student_id=student_id,
            enrollment_batch_id=batch_id,
            model_name=model_name,
            model_version=model_version,
            embedding_ciphertext=encrypted.ciphertext,
            encryption_key_id=encrypted.key_id,
            embedding_dimension=encrypted.dimension,
            quality_metadata=dict(result.quality_metadata),
            created_by_user_id=principal.id,
        )
        created.append(template)
        session.add(template)
    session.add(
        AuditLog(
            actor_user_id=principal.id,
            action="face_template.enrolled",
            entity_type="face_template_batch",
            entity_id=batch_id,
            after_state={
                "student_id": str(student_id),
                "model_name": model_name,
                "model_version": model_version,
                "template_count": len(created),
                "accepted_frames": len(accepted),
                "rejected_frames": rejected_count,
                "duplicate_warning_count": len(duplicate_warnings),
            },
        )
    )
    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        raise ApiProblem(
            409, "enrollment_conflict", "Enrollment tidak dapat disimpan."
        ) from exc
    return EnrollmentCaptureResultResponse(
        student_id=student_id,
        enrollment_batch_id=batch_id,
        template_status="enrolled",
        accepted_frames=len(accepted),
        rejected_frames=rejected_count,
        template_count=len(created),
        duplicate_warnings=duplicate_warnings,
        confirmation_required=True,
    )


@router.post(
    "/face-templates/{template_id}/revoke",
    response_model=TemplateRevocationResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Revoke all active templates in an enrollment batch",
)
def revoke_face_template_batch(
    template_id: UUID,
    principal: EnrollmentOperator,
    session: DbSession,
) -> TemplateRevocationResponse:
    selected = session.get(FaceTemplate, template_id)
    if selected is None:
        raise ApiProblem(404, "face_template_not_found", "Template tidak ditemukan.")
    if selected.revoked_at is not None:
        raise ApiProblem(
            409, "face_template_already_revoked", "Template sudah dicabut."
        )
    now = datetime.now(UTC)
    batch_templates = session.scalars(
        select(FaceTemplate).where(
            FaceTemplate.student_id == selected.student_id,
            FaceTemplate.enrollment_batch_id == selected.enrollment_batch_id,
            FaceTemplate.revoked_at.is_(None),
        )
    ).all()
    for template in batch_templates:
        template.revoked_at = now
        template.revoked_by_user_id = principal.id
        # A revoked biometric vector is no longer needed for recognition.
        template.embedding_ciphertext = None
        template.encryption_key_id = None
        template.embedding_dimension = None
    session.add(
        AuditLog(
            actor_user_id=principal.id,
            action="face_template.revoked",
            entity_type="face_template_batch",
            entity_id=selected.enrollment_batch_id,
            before_state={
                "student_id": str(selected.student_id),
                "template_count": len(batch_templates),
            },
            after_state={"revoked_at": now.isoformat()},
        )
    )
    session.commit()
    return TemplateRevocationResponse(
        student_id=selected.student_id,
        enrollment_batch_id=selected.enrollment_batch_id,
        revoked_templates=len(batch_templates),
        revoked_at=now,
    )


@router.get(
    "/face-templates",
    response_model=PageResponse[FaceTemplateResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List face template metadata without biometric vectors",
)
def list_face_templates(
    session: DbSession,
    principal: EnrollmentOperator,
    student_id: UUID | None = None,
    include_revoked: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[FaceTemplateResponse]:
    del principal
    query = select(FaceTemplate)
    count_query = select(func.count()).select_from(FaceTemplate)
    if student_id is not None:
        query = query.where(FaceTemplate.student_id == student_id)
        count_query = count_query.where(FaceTemplate.student_id == student_id)
    if not include_revoked:
        query = query.where(FaceTemplate.revoked_at.is_(None))
        count_query = count_query.where(FaceTemplate.revoked_at.is_(None))
    total = session.scalar(count_query) or 0
    rows = session.scalars(
        query.order_by(FaceTemplate.created_at.desc(), FaceTemplate.id)
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        FaceTemplateResponse(
            id=item.id,
            student_id=item.student_id,
            enrollment_batch_id=item.enrollment_batch_id,
            model_name=item.model_name,
            model_version=item.model_version,
            quality_metadata={
                key: value
                for key, value in item.quality_metadata.items()
                if isinstance(value, (str, int, float, bool)) or value is None
            },
            created_at=as_utc(item.created_at),
            revoked_at=as_utc(item.revoked_at) if item.revoked_at else None,
        )
        for item in rows
    ]
    return PageResponse(
        items=items, pagination=Pagination(total=total, limit=limit, offset=offset)
    )


def _find_duplicate_lookalikes(
    session: Session,
    keyring: FaceTemplateKeyring,
    *,
    student_id: UUID,
    model_name: str,
    model_version: str,
    new_embeddings: tuple[tuple[float, ...], ...],
) -> list[EnrollmentDuplicateWarning]:
    raw_threshold = os.getenv("PRESENSI_ENROLLMENT_DUPLICATE_WARNING_THRESHOLD", "0.85")
    try:
        threshold = float(raw_threshold)
    except ValueError as exc:
        raise ApiProblem(
            503, "duplicate_threshold_invalid", "Duplicate review threshold is invalid."
        ) from exc
    if not math.isfinite(threshold) or not -1 <= threshold <= 1:
        raise ApiProblem(
            503, "duplicate_threshold_invalid", "Duplicate review threshold is invalid."
        )

    rows = session.execute(
        select(FaceTemplate, Student.student_number, Student.full_name)
        .join(Student, Student.id == FaceTemplate.student_id)
        .where(
            FaceTemplate.student_id != student_id,
            FaceTemplate.model_name == model_name,
            FaceTemplate.model_version == model_version,
            FaceTemplate.revoked_at.is_(None),
            FaceTemplate.embedding_ciphertext.is_not(None),
            Student.is_active.is_(True),
        )
    ).all()
    max_by_student: dict[UUID, tuple[str, str, float]] = {}
    for template, student_number, full_name in rows:
        if (
            template.embedding_ciphertext is None
            or template.encryption_key_id is None
            or template.embedding_dimension is None
        ):
            continue
        try:
            existing = keyring.decrypt(
                template.embedding_ciphertext,
                dimension=template.embedding_dimension,
                key_id=template.encryption_key_id,
                template_id=template.id,
                student_id=template.student_id,
                model_name=template.model_name,
                model_version=template.model_version,
            )
        except BiometricCryptographyError as exc:
            raise ApiProblem(
                503,
                "face_template_unavailable",
                "Existing templates could not be compared safely.",
            ) from exc
        similarity = max(
            cosine_similarity(candidate, existing) for candidate in new_embeddings
        )
        current = max_by_student.get(template.student_id)
        if current is None or similarity > current[2]:
            max_by_student[template.student_id] = (
                student_number,
                full_name,
                similarity,
            )
    warnings = [
        EnrollmentDuplicateWarning(
            student_id=candidate_id,
            student_number=student_number,
            full_name=full_name,
            similarity=round(similarity, 5),
        )
        for candidate_id, (
            student_number,
            full_name,
            similarity,
        ) in max_by_student.items()
        if similarity >= threshold
    ]
    return sorted(warnings, key=lambda item: item.similarity, reverse=True)[:5]
