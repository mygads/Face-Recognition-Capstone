from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import Permission
from presensi_api.api.v1.routers._placeholder import feature_not_implemented
from presensi_api.api.v1.schemas.common import PageResponse
from presensi_api.api.v1.schemas.enrollment import (
    EnrollmentCaptureResultResponse,
    EnrollmentStudentStatusResponse,
    FaceTemplateResponse,
    TemplateEnrollmentRequest,
)
from presensi_api.db.models import ClassStudent, FaceTemplate, SchoolClass, Student
from presensi_api.db.session import get_db_session

router = APIRouter(tags=["enrollment", "templates"])
EnrollmentStatus = Literal["not_enrolled", "enrolled", "needs_reenrollment"]


@router.get(
    "/enrollments/class-status",
    response_model=list[EnrollmentStudentStatusResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List enrollment status for a class roster",
    dependencies=[Depends(require_permissions(Permission.ENROLLMENT_MANAGE))],
)
def list_class_enrollment_status(
    class_id: Annotated[UUID, Query()], session: Session = Depends(get_db_session)
) -> list[EnrollmentStudentStatusResponse]:
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
    summary="Enroll a face template",
    description=(
        "Contract placeholder; currently returns 501. The request intentionally "
        "contains no image, blob, or embedding payload."
    ),
    dependencies=[Depends(require_permissions(Permission.ENROLLMENT_MANAGE))],
)
def create_enrollment(
    request: TemplateEnrollmentRequest,
) -> FaceTemplateResponse:
    feature_not_implemented("template enrollment")


@router.post(
    "/enrollments/captures",
    response_model=EnrollmentCaptureResultResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Submit multiple student enrollment captures",
    description=(
        "Capture upload contract for the operator enrollment flow. Image processing "
        "and template creation are not available until biometric storage is approved."
    ),
    dependencies=[Depends(require_permissions(Permission.ENROLLMENT_MANAGE))],
)
def submit_enrollment_captures(
    student_id: UUID = Form(),
    captures: list[UploadFile] = File(),
) -> EnrollmentCaptureResultResponse:
    del student_id, captures
    feature_not_implemented("multi-frame enrollment processing")


@router.get(
    "/face-templates",
    response_model=PageResponse[FaceTemplateResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List face template metadata",
    description=(
        "Contract placeholder; currently returns 501 and exposes metadata only."
    ),
    dependencies=[Depends(require_permissions(Permission.ENROLLMENT_MANAGE))],
)
def list_face_templates(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[FaceTemplateResponse]:
    feature_not_implemented("face template metadata")
