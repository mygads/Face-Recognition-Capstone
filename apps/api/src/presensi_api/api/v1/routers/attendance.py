from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import (
    AuthenticatedUser,
    Permission,
    RoleCode,
)
from presensi_api.api.v1.routers._placeholder import feature_not_implemented
from presensi_api.api.v1.schemas.attendance import (
    AttendanceCorrectionRequest,
    AttendanceCorrectionResponse,
    AttendanceRecordResponse,
    AttendanceStatus,
    RecognitionEventDecisionResponse,
    RecognitionEventRequest,
)
from presensi_api.api.v1.schemas.common import PageResponse
from presensi_api.attendance_decision import decide_recognition_event
from presensi_api.db.models import (
    AttendanceCorrection,
    AttendanceRecord,
    AttendanceSession,
    AuditLog,
    PracticumSchedule,
)
from presensi_api.db.session import get_db_session
from presensi_api.session_lifecycle import as_utc

router = APIRouter(prefix="/attendance", tags=["attendance"])
DbSession = Annotated[Session, Depends(get_db_session)]
AttendanceOperator = Annotated[
    AuthenticatedUser, Depends(require_permissions(Permission.SESSION_OPERATE))
]


@router.post(
    "/recognition-events",
    response_model=RecognitionEventDecisionResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Record an AI recognition event and decide attendance",
    description=(
        "Stores the recognition event for audit. Creates a final attendance record "
        "only when device, session, roster, liveness, and duplicate rules pass."
    ),
)
def ingest_recognition_event(
    request: RecognitionEventRequest,
    principal: AttendanceOperator,
    session: DbSession,
) -> RecognitionEventDecisionResponse:
    return decide_recognition_event(session, request, principal)


@router.get(
    "",
    response_model=PageResponse[AttendanceRecordResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List final attendance records",
    description="Contract placeholder; currently returns 501.",
    dependencies=[Depends(require_permissions(Permission.ATTENDANCE_READ))],
)
def list_attendance(
    session_id: UUID | None = None,
    student_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[AttendanceRecordResponse]:
    feature_not_implemented("attendance records")


@router.post(
    "/corrections",
    response_model=AttendanceCorrectionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Create an audited pending attendance correction request",
    description=(
        "Stores a teacher correction request for a schedule they own. The request "
        "remains pending and does not change final attendance until an approval "
        "policy and decision workflow are implemented."
    ),
)
def request_attendance_correction(
    request: AttendanceCorrectionRequest,
    principal: Annotated[
        AuthenticatedUser, Depends(require_permissions(Permission.ATTENDANCE_CORRECT))
    ],
    session: DbSession,
) -> AttendanceCorrectionResponse:
    record = session.get(AttendanceRecord, request.attendance_record_id)
    if record is None:
        raise ApiProblem(
            404, "attendance_record_not_found", "Presensi tidak ditemukan."
        )
    attendance_session = session.get(AttendanceSession, record.session_id)
    schedule = (
        session.get(PracticumSchedule, attendance_session.practicum_schedule_id)
        if attendance_session is not None
        else None
    )
    if schedule is None:
        raise ApiProblem(
            404, "attendance_record_not_found", "Presensi tidak ditemukan."
        )
    if (
        RoleCode.TEACHER in principal.roles
        and RoleCode.ADMIN not in principal.roles
        and schedule.teacher_user_id != principal.id
    ):
        raise ApiProblem(
            404, "attendance_record_not_found", "Presensi tidak ditemukan."
        )

    correction = AttendanceCorrection(
        attendance_record_id=record.id,
        requested_by_user_id=principal.id,
        previous_status=record.status,
        corrected_status=request.corrected_status,
        reason=request.reason,
        decision_status="pending",
    )
    session.add(correction)
    session.flush()
    session.add(
        AuditLog(
            actor_user_id=principal.id,
            action="attendance.correction.requested",
            entity_type="attendance_correction",
            entity_id=correction.id,
            after_state={
                "attendance_record_id": str(record.id),
                "previous_status": record.status,
                "corrected_status": request.corrected_status,
                "decision_status": "pending",
            },
        )
    )
    session.commit()
    session.refresh(correction)
    return AttendanceCorrectionResponse(
        id=correction.id,
        attendance_record_id=correction.attendance_record_id,
        previous_status=cast(AttendanceStatus, correction.previous_status),
        corrected_status=cast(AttendanceStatus, correction.corrected_status),
        decision_status="pending",
        reason=correction.reason,
        created_at=as_utc(correction.created_at),
        decided_at=(
            as_utc(correction.decided_at) if correction.decided_at is not None else None
        ),
    )
