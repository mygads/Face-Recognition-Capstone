from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import (
    AuthenticatedUser,
    Permission,
    RoleCode,
)
from presensi_api.api.v1.schemas.attendance import (
    AttendanceRecordResponse,
    AttendanceSource,
    AttendanceStatus,
    ManualMarkRequest,
    ManualMarkResponse,
    RecognitionEventDecisionResponse,
    RecognitionEventRequest,
)
from presensi_api.api.v1.schemas.common import PageResponse, Pagination
from presensi_api.attendance_decision import decide_recognition_event
from presensi_api.attendance_manual import mark_manual_attendance
from presensi_api.db.models import (
    AttendanceRecord,
    AttendanceSession,
    PracticumSchedule,
)
from presensi_api.db.session import get_db_session
from presensi_api.session_lifecycle import as_utc

router = APIRouter(prefix="/attendance", tags=["attendance"])
DbSession = Annotated[Session, Depends(get_db_session)]
AttendanceOperator = Annotated[
    AuthenticatedUser, Depends(require_permissions(Permission.SESSION_OPERATE))
]
ManualMarkOperator = Annotated[
    AuthenticatedUser, Depends(require_permissions(Permission.ATTENDANCE_MANUAL))
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


@router.post(
    "/sessions/{session_id}/manual-marks",
    response_model=ManualMarkResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Record or directly update a manual attendance mark",
    description=(
        "Stores a final attendance record for a roster member, or directly "
        "updates the existing record (pengganti alur koreksi: tanpa "
        "persetujuan admin). Closed sessions accept a separate post-session "
        "correction permission (alasan wajib, tercatat audit). "
        "Never accepts image or embedding fields."
    ),
)
def create_manual_mark(
    session_id: UUID,
    request: ManualMarkRequest,
    principal: ManualMarkOperator,
    session: DbSession,
) -> ManualMarkResponse:
    record = mark_manual_attendance(session, session_id, request, principal)
    return ManualMarkResponse(
        record=AttendanceRecordResponse(
            id=record.id,
            session_id=record.session_id,
            student_id=record.student_id,
            status=cast(AttendanceStatus, record.status),
            source=cast(AttendanceSource, record.source),
            recognition_event_id=record.recognition_event_id,
            recorded_at=as_utc(record.recorded_at),
            occurred_at=as_utc(record.occurred_at)
            if record.occurred_at is not None
            else None,
            rule_version=record.rule_version,
            note=record.note,
        )
    )


@router.get(
    "",
    response_model=PageResponse[AttendanceRecordResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List final attendance records",
    description=(
        "Final attendance only: one row per student/session after session, "
        "roster, liveness, and duplicate validation. Teachers see only "
        "their own schedules."
    ),
)
def list_attendance(
    principal: Annotated[
        AuthenticatedUser, Depends(require_permissions(Permission.ATTENDANCE_READ))
    ],
    session: DbSession,
    session_id: UUID | None = None,
    student_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[AttendanceRecordResponse]:
    query = (
        select(AttendanceRecord)
        .join(
            AttendanceSession,
            AttendanceSession.id == AttendanceRecord.session_id,
        )
        .join(
            PracticumSchedule,
            PracticumSchedule.id == AttendanceSession.practicum_schedule_id,
        )
    )
    if RoleCode.ADMIN not in principal.roles:
        if RoleCode.TEACHER in principal.roles:
            from presensi_api.api.security.scope import (
                teacher_class_ids as _tc,
            )

            _classes = _tc(session, principal.id)
            if _classes:
                query = query.where(
                    (PracticumSchedule.class_id.in_(_classes))
                    | (PracticumSchedule.teacher_user_id == principal.id)
                )
            else:
                query = query.where(PracticumSchedule.teacher_user_id == principal.id)
        elif RoleCode.LABORANT in principal.roles:
            from presensi_api.api.security.scope import laborant_lab_ids as _ll

            _labs = _ll(session, principal.id)
            if _labs:
                query = query.where(PracticumSchedule.laboratory_id.in_(_labs))
            else:
                query = query.where(PracticumSchedule.id.is_(None))
    if session_id is not None:
        query = query.where(AttendanceRecord.session_id == session_id)
    if student_id is not None:
        query = query.where(AttendanceRecord.student_id == student_id)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(
        query.order_by(AttendanceRecord.recorded_at.desc(), AttendanceRecord.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return PageResponse(
        items=[
            AttendanceRecordResponse(
                id=row.id,
                session_id=row.session_id,
                student_id=row.student_id,
                status=cast(AttendanceStatus, row.status),
                source=cast(AttendanceSource, row.source),
                recognition_event_id=row.recognition_event_id,
                recorded_at=as_utc(row.recorded_at),
                occurred_at=as_utc(row.occurred_at)
                if row.occurred_at is not None
                else None,
                rule_version=row.rule_version,
                note=row.note,
            )
            for row in rows
        ],
        pagination=Pagination(total=total, limit=limit, offset=offset),
    )
