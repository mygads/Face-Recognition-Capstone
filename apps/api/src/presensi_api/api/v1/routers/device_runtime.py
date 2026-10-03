from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.device_credentials import (
    AuthenticatedDevice,
    require_path_device,
    rotate_device_credential,
)
from presensi_api.api.security.request_rate_limit import DeviceActor
from presensi_api.api.security.roles import AuthenticatedUser, Permission
from presensi_api.api.v1.schemas.attendance import (
    RecognitionEventDecisionResponse,
    RecognitionEventRequest,
)
from presensi_api.api.v1.schemas.device_runtime import (
    ActiveDeviceSessionResponse,
    ActiveSessionCacheResponse,
    DeviceCredentialResponse,
    DeviceCredentialRotationRequest,
    DeviceHeartbeatDeviceResponse,
    DeviceRuntimeStatusResponse,
    PreviewGalleryResponse,
    SessionRosterStudentResponse,
    SessionTemplateResponse,
)
from presensi_api.api.v1.schemas.laboratories import DeviceHeartbeatRequest
from presensi_api.attendance_decision import decide_recognition_event
from presensi_api.biometric_crypto import (
    BiometricCryptographyError,
    require_face_template_keyring,
)
from presensi_api.db.models import (
    AttendanceSession,
    AuditLog,
    ClassStudent,
    Device,
    FaceTemplate,
    PracticumSchedule,
    SchoolClass,
    SessionStudent,
    Student,
)
from presensi_api.db.session import get_db_session
from presensi_api.session_lifecycle import (
    as_utc,
    close_expired_sessions,
    scheduled_end_at,
)

router = APIRouter(tags=["device-runtime"])
DbSession = Annotated[Session, Depends(get_db_session)]


def _session_end(schedule: PracticumSchedule, opened_at: datetime) -> datetime:
    try:
        return scheduled_end_at(schedule, opened_at)
    except (ValueError, TypeError) as exc:
        raise ApiProblem(
            409, "session_schedule_invalid", "The active session schedule is invalid."
        ) from exc


def _active_device_sessions(
    session: Session,
    device: Device,
    *,
    now: datetime,
) -> list[tuple[AttendanceSession, PracticumSchedule, datetime]]:
    close_expired_sessions(session, now=now)
    rows = session.execute(
        select(AttendanceSession, PracticumSchedule)
        .join(
            PracticumSchedule,
            PracticumSchedule.id == AttendanceSession.practicum_schedule_id,
        )
        .where(
            AttendanceSession.status == "active",
            PracticumSchedule.laboratory_id == device.laboratory_id,
        )
        .order_by(AttendanceSession.opened_at, AttendanceSession.id)
    ).all()
    active: list[tuple[AttendanceSession, PracticumSchedule, datetime]] = []
    for attendance_session, schedule in rows:
        end_at = _session_end(schedule, attendance_session.opened_at)
        if end_at > now:
            active.append((attendance_session, schedule, end_at))
    return active


def _device_for_path(actor: AuthenticatedDevice, device_id: UUID) -> Device:
    return require_path_device(actor, device_id)


def _template_roster(
    rows: list[tuple[UUID, str, str, str, FaceTemplate | None]],
    *,
    model_name: str,
    model_version: str,
) -> tuple[list[SessionRosterStudentResponse], int]:
    keyring = require_face_template_keyring()
    grouped: dict[UUID, dict[str, object]] = {}
    template_count = 0
    for student_id, student_number, full_name, class_name, template in rows:
        student = grouped.setdefault(
            student_id,
            {
                "student_id": student_id,
                "student_number": student_number,
                "full_name": full_name,
                "class_names": set(),
                "templates": [],
            },
        )
        class_names = student["class_names"]
        assert isinstance(class_names, set)
        class_names.add(class_name)
        if template is None:
            continue
        if (
            template.embedding_ciphertext is None
            or template.encryption_key_id is None
            or template.embedding_dimension is None
        ):
            continue
        try:
            values = keyring.decrypt(
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
                "A stored template could not be loaded safely.",
            ) from exc
        templates = student["templates"]
        assert isinstance(templates, list)
        templates.append(
            SessionTemplateResponse(
                model_name=template.model_name,
                model_version=template.model_version,
                values=list(values),
                normalized=True,
            )
        )
        template_count += 1
    return (
        [
            SessionRosterStudentResponse(
                student_id=cast(UUID, item["student_id"]),
                student_number=cast(str, item["student_number"]),
                full_name=cast(str, item["full_name"]),
                class_names=sorted(cast(set[str], item["class_names"])),
                templates=cast(list[SessionTemplateResponse], item["templates"]),
            )
            for item in grouped.values()
        ],
        template_count,
    )


@router.post(
    "/devices/{device_id}/credentials",
    response_model=DeviceCredentialResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Provision a one-time device credential",
    dependencies=[Depends(require_permissions(Permission.MANAGE_MASTER_DATA))],
)
def provision_device_credential(
    device_id: UUID,
    session: DbSession,
    principal: Annotated[
        AuthenticatedUser, Depends(require_permissions(Permission.MANAGE_MASTER_DATA))
    ],
) -> DeviceCredentialResponse:
    device = session.get(Device, device_id)
    if device is None or not device.is_active:
        raise ApiProblem(404, "device_not_found", "Perangkat aktif tidak ditemukan.")
    if device.credential_hash is not None:
        raise ApiProblem(
            409, "device_credential_exists", "Perangkat sudah memiliki kredensial."
        )
    token, expires_at, _ = rotate_device_credential(device)
    session.add(
        AuditLog(
            actor_user_id=principal.id,
            action="device.credential_provisioned",
            entity_type="device",
            entity_id=device.id,
            after_state={"credential_expires_at": expires_at.isoformat()},
        )
    )
    session.commit()
    return DeviceCredentialResponse(
        device_id=device.id, token=token, expires_at=expires_at
    )


@router.post(
    "/devices/{device_id}/credentials/rotate",
    response_model=DeviceCredentialResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Rotate a device credential with a short overlap",
    dependencies=[Depends(require_permissions(Permission.MANAGE_MASTER_DATA))],
)
def rotate_provisioned_device_credential(
    device_id: UUID,
    request: DeviceCredentialRotationRequest,
    session: DbSession,
    principal: Annotated[
        AuthenticatedUser, Depends(require_permissions(Permission.MANAGE_MASTER_DATA))
    ],
) -> DeviceCredentialResponse:
    device = session.get(Device, device_id)
    if device is None or not device.is_active:
        raise ApiProblem(404, "device_not_found", "Perangkat aktif tidak ditemukan.")
    token, expires_at, previous_until = rotate_device_credential(device)
    session.add(
        AuditLog(
            actor_user_id=principal.id,
            action="device.credential_rotated",
            entity_type="device",
            entity_id=device.id,
            after_state={
                "reason": request.reason,
                "credential_expires_at": expires_at.isoformat(),
                "previous_credential_valid_until": (
                    previous_until.isoformat() if previous_until else None
                ),
            },
        )
    )
    session.commit()
    return DeviceCredentialResponse(
        device_id=device.id,
        token=token,
        expires_at=expires_at,
        previous_token_valid_until=previous_until,
    )


@router.post(
    "/devices/{device_id}/credentials/renew",
    response_model=DeviceCredentialResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Renew an expiring device credential",
)
def renew_device_credential(
    device_id: UUID,
    principal: DeviceActor,
    session: DbSession,
) -> DeviceCredentialResponse:
    device = _device_for_path(principal, device_id)
    if not principal.used_current_credential:
        raise HTTPException(status_code=401, detail="Current credential required.")
    token, expires_at, previous_until = rotate_device_credential(device)
    session.add(
        AuditLog(
            actor_user_id=None,
            action="device.credential_renewed",
            entity_type="device",
            entity_id=device.id,
            after_state={
                "credential_expires_at": expires_at.isoformat(),
                "previous_credential_valid_until": (
                    previous_until.isoformat() if previous_until else None
                ),
            },
        )
    )
    session.commit()
    return DeviceCredentialResponse(
        device_id=device.id,
        token=token,
        expires_at=expires_at,
        previous_token_valid_until=previous_until,
    )


@router.get(
    "/devices/{device_id}/active-sessions",
    response_model=list[ActiveDeviceSessionResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Discover active sessions in this device's laboratory",
)
def discover_active_sessions(
    device_id: UUID,
    principal: DeviceActor,
    session: DbSession,
) -> list[ActiveDeviceSessionResponse]:
    device = _device_for_path(principal, device_id)
    now = datetime.now(UTC)
    active = _active_device_sessions(session, device, now=now)
    expiry = now + timedelta(seconds=_gallery_max_age_seconds())
    return [
        ActiveDeviceSessionResponse(
            session_id=item.id,
            session_status="active",
            session_starts_at=as_utc(item.opened_at),
            session_ends_at=end_at,
            generated_at=now,
            expires_at=min(expiry, end_at),
        )
        for item, _schedule, end_at in active
    ]


@router.get(
    "/devices/{device_id}/device-status",
    response_model=DeviceRuntimeStatusResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Validate an active device credential",
)
def get_device_runtime_status(
    device_id: UUID,
    principal: DeviceActor,
) -> DeviceRuntimeStatusResponse:
    device = _device_for_path(principal, device_id)
    return DeviceRuntimeStatusResponse(
        device_id=device.id,
        active=True,
        deployment_profile=cast(
            Literal["AI_EDGE", "STB_GATEWAY"], device.deployment_profile
        ),
    )


@router.get(
    "/devices/{device_id}/active-session-cache",
    response_model=ActiveSessionCacheResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary=(
        "Fetch the active session roster and encrypted templates for local inference"
    ),
)
def get_active_session_cache(
    device_id: UUID,
    principal: DeviceActor,
    session: DbSession,
    model_name: Annotated[str, Query(min_length=1, max_length=120)],
    model_version: Annotated[str, Query(min_length=1, max_length=80)],
    session_id: UUID | None = None,
) -> ActiveSessionCacheResponse:
    device = _device_for_path(principal, device_id)
    if not device.camera_enabled:
        raise ApiProblem(
            409, "device_camera_disabled", "Kamera perangkat sedang dijeda admin."
        )
    now = datetime.now(UTC)
    active = _active_device_sessions(session, device, now=now)
    if session_id is None:
        if len(active) > 1:
            raise ApiProblem(
                409,
                "multiple_active_sessions",
                "More than one attendance session is active in this laboratory.",
            )
        if not active:
            raise ApiProblem(
                404, "active_session_not_found", "Tidak ada sesi aktif di laboratorium."
            )
        selected, schedule, end_at = active[0]
    else:
        selected_row = next((item for item in active if item[0].id == session_id), None)
        if selected_row is None:
            raise ApiProblem(
                404,
                "active_session_not_found",
                "Sesi aktif tidak ditemukan untuk perangkat ini.",
            )
        selected, schedule, end_at = selected_row

    roster_rows = session.execute(
        select(
            SessionStudent.student_id,
            SessionStudent.student_number_snapshot,
            SessionStudent.full_name_snapshot,
            SchoolClass.name,
            FaceTemplate,
        )
        .join(AttendanceSession, AttendanceSession.id == SessionStudent.session_id)
        .join(
            PracticumSchedule,
            PracticumSchedule.id == AttendanceSession.practicum_schedule_id,
        )
        .join(SchoolClass, SchoolClass.id == PracticumSchedule.class_id)
        .outerjoin(
            FaceTemplate,
            (FaceTemplate.student_id == SessionStudent.student_id)
            & (FaceTemplate.revoked_at.is_(None))
            & (FaceTemplate.model_name == model_name)
            & (FaceTemplate.model_version == model_version),
        )
        .where(SessionStudent.session_id == selected.id)
        .order_by(SessionStudent.student_number_snapshot, SessionStudent.student_id)
    ).all()
    roster, template_count = _template_roster(
        list(roster_rows), model_name=model_name, model_version=model_version
    )
    if template_count == 0:
        raise ApiProblem(
            409,
            "session_gallery_empty",
            "Tidak ada template aktif yang sesuai dengan model perangkat.",
        )

    generated_at = datetime.now(UTC)
    expires_at = min(
        end_at,
        generated_at + timedelta(seconds=_gallery_max_age_seconds()),
    )
    return ActiveSessionCacheResponse(
        device_id=device.id,
        session_id=selected.id,
        session_status="active",
        session_starts_at=as_utc(selected.opened_at),
        session_ends_at=end_at,
        generated_at=generated_at,
        expires_at=expires_at,
        model_name=model_name,
        model_version=model_version,
        roster=roster,
    )


@router.get(
    "/devices/{device_id}/preview-gallery",
    response_model=PreviewGalleryResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Fetch the time- and laboratory-scoped preview gallery",
)
def get_preview_gallery(
    device_id: UUID,
    principal: DeviceActor,
    session: DbSession,
    model_name: Annotated[str, Query(min_length=1, max_length=120)],
    model_version: Annotated[str, Query(min_length=1, max_length=80)],
) -> PreviewGalleryResponse:
    device = _device_for_path(principal, device_id)
    if device.deployment_profile != "AI_EDGE":
        raise ApiProblem(
            409,
            "preview_gallery_profile_unsupported",
            "Preview gallery hanya tersedia untuk AI_EDGE.",
        )
    if not device.camera_enabled:
        raise ApiProblem(
            409, "device_camera_disabled", "Kamera perangkat sedang dijeda admin."
        )
    now = datetime.now(UTC)
    if _active_device_sessions(session, device, now=now):
        raise ApiProblem(
            409,
            "preview_gallery_session_active",
            "Gunakan roster snapshot sesi aktif untuk pengenalan presensi.",
        )
    schedules = session.scalars(
        select(PracticumSchedule)
        .join(SchoolClass, SchoolClass.id == PracticumSchedule.class_id)
        .where(
            PracticumSchedule.laboratory_id == device.laboratory_id,
            PracticumSchedule.is_active.is_(True),
            SchoolClass.is_active.is_(True),
        )
    ).all()
    eligible_class_ids: set[UUID] = set()
    for schedule in schedules:
        try:
            local_now = now.astimezone(ZoneInfo(schedule.timezone_name))
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            continue
        if (
            local_now.weekday() != schedule.weekday
            or local_now.date() < schedule.effective_from
            or (
                schedule.effective_through is not None
                and local_now.date() > schedule.effective_through
            )
        ):
            continue
        # A preview may begin shortly before class, but ends with the scheduled
        # class. Keep the off-session gallery limited to today's lab schedule.
        local_minutes = local_now.hour * 60 + local_now.minute
        start_minutes = schedule.start_time.hour * 60 + schedule.start_time.minute
        end_minutes = schedule.end_time.hour * 60 + schedule.end_time.minute
        if start_minutes - 15 <= local_minutes < end_minutes:
            eligible_class_ids.add(schedule.class_id)
    if not eligible_class_ids:
        raise ApiProblem(
            404,
            "preview_gallery_unavailable",
            "Tidak ada kelas terjadwal untuk perangkat ini saat ini.",
        )

    rows = session.execute(
        select(
            Student.id,
            Student.student_number,
            Student.full_name,
            SchoolClass.name,
            FaceTemplate,
        )
        .join(ClassStudent, ClassStudent.student_id == Student.id)
        .join(SchoolClass, SchoolClass.id == ClassStudent.class_id)
        .outerjoin(
            FaceTemplate,
            (FaceTemplate.student_id == Student.id)
            & (FaceTemplate.revoked_at.is_(None))
            & (FaceTemplate.model_name == model_name)
            & (FaceTemplate.model_version == model_version),
        )
        .where(
            ClassStudent.class_id.in_(eligible_class_ids),
            Student.is_active.is_(True),
        )
        .order_by(Student.student_number, Student.id, SchoolClass.name)
    ).all()
    roster, template_count = _template_roster(
        list(rows), model_name=model_name, model_version=model_version
    )
    if template_count == 0:
        raise ApiProblem(
            409,
            "preview_gallery_empty",
            "Belum ada template aktif untuk kelas terjadwal di laboratorium ini.",
        )
    generated_at = datetime.now(UTC)
    return PreviewGalleryResponse(
        device_id=device.id,
        generated_at=generated_at,
        expires_at=generated_at + timedelta(seconds=_gallery_max_age_seconds()),
        model_name=model_name,
        model_version=model_version,
        roster=roster,
    )


@router.post(
    "/devices/{device_id}/device-heartbeat",
    response_model=DeviceHeartbeatDeviceResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Record a device heartbeat using its own credential",
)
def device_heartbeat(
    device_id: UUID,
    principal: DeviceActor,
    session: DbSession,
    request: DeviceHeartbeatRequest | None = None,
) -> DeviceHeartbeatDeviceResponse:
    device = _device_for_path(principal, device_id)
    if request is not None:
        if (
            request.deployment_profile is not None
            and request.deployment_profile != device.deployment_profile
        ):
            raise ApiProblem(
                409,
                "deployment_profile_mismatch",
                "Profil heartbeat tidak sesuai dengan registry perangkat.",
            )
        for key in ("app_version", "model_version", "camera_status"):
            value = getattr(request, key)
            if value is not None:
                setattr(device, key, value)
        if request.latency_summary is not None:
            device.latency_summary = request.latency_summary.model_dump(
                exclude_unset=True
            )
        if request.camera_metrics is not None:
            device.camera_metrics = request.camera_metrics.model_dump(
                mode="json", exclude_unset=True
            )
    now = datetime.now(UTC)
    device.last_seen_at = now
    if device.credential_expires_at is None:
        raise HTTPException(status_code=401, detail="Device credential has expired.")
    session.commit()
    return DeviceHeartbeatDeviceResponse(
        device_id=device.id,
        last_seen_at=now,
        credential_expires_at=as_utc(device.credential_expires_at),
    )


@router.post(
    "/devices/{device_id}/recognition-events",
    response_model=RecognitionEventDecisionResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Submit an idempotent recognition event using a device credential",
)
def device_recognition_event(
    device_id: UUID,
    request: RecognitionEventRequest,
    principal: DeviceActor,
    session: DbSession,
) -> RecognitionEventDecisionResponse:
    device = _device_for_path(principal, device_id)
    if request.device_id != device.id:
        raise ApiProblem(
            403, "device_id_mismatch", "Event device does not match its credential."
        )
    return decide_recognition_event(session, request, None)


def _gallery_max_age_seconds() -> int:
    raw = os.getenv("PRESENSI_GALLERY_MAX_AGE_SECONDS", "300")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ApiProblem(
            503,
            "gallery_configuration_invalid",
            "Gallery cache configuration is invalid.",
        ) from exc
    if not 5 <= value <= 86400:
        raise ApiProblem(
            503,
            "gallery_configuration_invalid",
            "Gallery cache configuration is invalid.",
        )
    return value
