from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import AuthenticatedUser, Permission, RoleCode
from presensi_api.api.v1.schemas.attendance import AttendanceStatus
from presensi_api.api.v1.schemas.common import PageResponse, Pagination
from presensi_api.api.v1.schemas.sessions import (
    AttendanceSessionCreateRequest,
    AttendanceSessionResponse,
    OpenableScheduleResponse,
    SessionOpeningPolicy,
    SessionOpeningPolicyResponse,
    SessionRosterEntry,
    TeacherOpeningPreference,
    TeacherOpeningPreferenceResponse,
)
from presensi_api.db.models import (
    AttendanceRecord,
    AttendanceSession,
    AuditLog,
    ClassStudent,
    Laboratory,
    PracticumSchedule,
    SchoolClass,
    SessionStudent,
    Student,
    User,
)
from presensi_api.db.session import get_db_session
from presensi_api.runtime_configuration import (
    SESSION_OPENING_POLICY_SCOPE,
    save_configuration,
    session_opening_policy,
)
from presensi_api.session_lifecycle import (
    RUNNING_SESSION_STATUSES,
    as_utc,
    close_expired_sessions,
    scheduled_end_at,
    scheduled_start_at,
    session_can_open_today,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])
DbSession = Annotated[Session, Depends(get_db_session)]
SessionOperator = Annotated[
    AuthenticatedUser, Depends(require_permissions(Permission.SESSION_OPERATE))
]
SessionPolicyManager = Annotated[
    AuthenticatedUser, Depends(require_permissions(Permission.MANAGE_SETTINGS))
]
SessionStatus = Literal["active", "manual_override", "closed", "cancelled"]


def _teacher_scope_allows(
    principal: AuthenticatedUser, schedule: PracticumSchedule
) -> bool:
    return RoleCode.ADMIN in principal.roles or (
        RoleCode.TEACHER not in principal.roles
        or schedule.teacher_user_id == principal.id
    )


def _schedule_for_open(
    session: Session, schedule_id: UUID, principal: AuthenticatedUser
) -> PracticumSchedule:
    schedule = session.get(PracticumSchedule, schedule_id)
    if (
        schedule is None
        or not schedule.is_active
        or not _teacher_scope_allows(principal, schedule)
    ):
        raise ApiProblem(404, "schedule_not_found", "Jadwal aktif tidak ditemukan.")
    school_class = session.get(SchoolClass, schedule.class_id)
    laboratory = session.get(Laboratory, schedule.laboratory_id)
    teacher = session.get(User, schedule.teacher_user_id)
    if (
        school_class is None
        or not school_class.is_active
        or laboratory is None
        or not laboratory.is_active
        or teacher is None
        or not teacher.is_active
    ):
        raise ApiProblem(
            409,
            "schedule_references_inactive",
            "Kelas, laboratorium, atau guru pada jadwal sudah nonaktif.",
        )
    return schedule


def _can_open_today(schedule: PracticumSchedule, now: datetime) -> None:
    try:
        allowed, reason = session_can_open_today(schedule, now)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ApiProblem(
            422, "invalid_schedule_timezone", "Zona waktu jadwal tidak valid."
        ) from exc
    if not allowed:
        raise ApiProblem(
            409, "schedule_not_openable", reason or "Jadwal belum dapat dibuka."
        )


def _session_response(
    session: Session, item: AttendanceSession
) -> AttendanceSessionResponse:
    schedule = session.get(PracticumSchedule, item.practicum_schedule_id)
    assert schedule is not None
    school_class = session.get(SchoolClass, schedule.class_id)
    laboratory = session.get(Laboratory, schedule.laboratory_id)
    teacher = session.get(User, schedule.teacher_user_id)
    assert school_class is not None and laboratory is not None and teacher is not None
    student_count = (
        session.scalar(
            select(func.count())
            .select_from(SessionStudent)
            .where(SessionStudent.session_id == item.id)
        )
        or 0
    )
    return AttendanceSessionResponse(
        id=item.id,
        practicum_schedule_id=item.practicum_schedule_id,
        status=cast(SessionStatus, item.status),
        opened_automatically=item.opened_by_user_id is None,
        opened_at=as_utc(item.opened_at),
        closed_at=as_utc(item.closed_at) if item.closed_at is not None else None,
        grace_period_minutes=item.grace_period_minutes,
        student_count=student_count,
        subject=schedule.subject,
        class_name=school_class.name,
        laboratory_name=laboratory.name,
        teacher_name=teacher.full_name,
        weekday=schedule.weekday,
        start_time=schedule.start_time,
        end_time=schedule.end_time,
        timezone_name=schedule.timezone_name,
        scheduled_end_at=scheduled_end_at(schedule, item.opened_at),
    )


def _openable_schedule_response(
    session: Session, schedule: PracticumSchedule
) -> OpenableScheduleResponse:
    school_class = session.get(SchoolClass, schedule.class_id)
    laboratory = session.get(Laboratory, schedule.laboratory_id)
    teacher = session.get(User, schedule.teacher_user_id)
    assert school_class is not None and laboratory is not None and teacher is not None
    return OpenableScheduleResponse(
        id=schedule.id,
        subject=schedule.subject,
        class_name=school_class.name,
        laboratory_name=laboratory.name,
        teacher_name=teacher.full_name,
        weekday=schedule.weekday,
        start_time=schedule.start_time,
        end_time=schedule.end_time,
        timezone_name=schedule.timezone_name,
    )


@router.get(
    "/openable-schedules",
    response_model=list[OpenableScheduleResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List schedules that can open a session today",
)
def list_openable_schedules(
    principal: SessionOperator,
    session: DbSession,
) -> list[OpenableScheduleResponse]:
    # Manual open is always available as the override path, regardless of any
    # global automatic policy or the teacher's own opening mode.
    now = datetime.now(UTC)
    query = (
        select(PracticumSchedule)
        .join(SchoolClass, SchoolClass.id == PracticumSchedule.class_id)
        .join(Laboratory, Laboratory.id == PracticumSchedule.laboratory_id)
        .join(User, User.id == PracticumSchedule.teacher_user_id)
        .where(
            PracticumSchedule.is_active.is_(True),
            SchoolClass.is_active.is_(True),
            Laboratory.is_active.is_(True),
            User.is_active.is_(True),
        )
    )
    if RoleCode.TEACHER in principal.roles and RoleCode.ADMIN not in principal.roles:
        query = query.where(PracticumSchedule.teacher_user_id == principal.id)
    result = []
    for schedule in session.scalars(query).all():
        try:
            allowed, _ = session_can_open_today(schedule, now)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            allowed = False
        if allowed:
            result.append(_openable_schedule_response(session, schedule))
    return result


@router.get(
    "",
    response_model=PageResponse[AttendanceSessionResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List attendance sessions",
)
def list_sessions(
    principal: SessionOperator,
    session: DbSession,
    session_status: Annotated[SessionStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[AttendanceSessionResponse]:
    close_expired_sessions(session)
    query = select(AttendanceSession).join(
        PracticumSchedule,
        PracticumSchedule.id == AttendanceSession.practicum_schedule_id,
    )
    if RoleCode.TEACHER in principal.roles and RoleCode.ADMIN not in principal.roles:
        query = query.where(PracticumSchedule.teacher_user_id == principal.id)
    if session_status is not None:
        query = query.where(AttendanceSession.status == session_status)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    sessions = session.scalars(
        query.order_by(AttendanceSession.opened_at.desc()).limit(limit).offset(offset)
    ).all()
    return PageResponse(
        items=[_session_response(session, item) for item in sessions],
        pagination=Pagination(total=total, limit=limit, offset=offset),
    )


@router.get(
    "/policy",
    response_model=SessionOpeningPolicyResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Read the attendance session opening policy",
)
def get_session_policy(
    principal: SessionOperator,
    session: DbSession,
) -> SessionOpeningPolicyResponse:
    revision, policy, updated_at = session_opening_policy(session)
    return SessionOpeningPolicyResponse(
        **SessionOpeningPolicy.model_validate(policy).model_dump(),
        revision=revision,
        updated_at=as_utc(updated_at) if updated_at is not None else None,
    )


@router.put(
    "/policy",
    response_model=SessionOpeningPolicyResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Publish attendance session opening policy",
)
def put_session_policy(
    request: SessionOpeningPolicy,
    session: DbSession,
    actor: SessionPolicyManager,
) -> SessionOpeningPolicyResponse:
    version = save_configuration(
        session,
        scope_key=SESSION_OPENING_POLICY_SCOPE,
        settings=request.model_dump(mode="json"),
        actor=actor,
    )
    return SessionOpeningPolicyResponse(
        **request.model_dump(),
        revision=version.revision,
        updated_at=as_utc(version.created_at),
    )


@router.post(
    "",
    response_model=AttendanceSessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Open an attendance session and snapshot its roster",
)
def open_session(
    request: AttendanceSessionCreateRequest,
    principal: SessionOperator,
    session: DbSession,
) -> AttendanceSessionResponse:
    now = datetime.now(UTC)
    close_expired_sessions(session, now=now)
    _revision, opening_policy, _updated_at = session_opening_policy(session)
    schedule = _schedule_for_open(session, request.practicum_schedule_id, principal)
    _can_open_today(schedule, now)
    active_session = session.scalar(
        select(AttendanceSession.id).where(
            AttendanceSession.practicum_schedule_id == schedule.id,
            AttendanceSession.status.in_(RUNNING_SESSION_STATUSES),
        )
    )
    if active_session is not None:
        raise ApiProblem(
            409,
            "session_already_active",
            "Sesi untuk jadwal ini masih terbuka.",
        )

    # A manual open inside the automatic window behaves like a worker-opened
    # session; outside the window it is recorded as a manual override.
    try:
        scheduled_start = scheduled_start_at(schedule, now)
        schedule_end = scheduled_end_at(schedule, now)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        scheduled_start = None
        schedule_end = None
    before = opening_policy.get("auto_open_minutes_before", 0)
    after = opening_policy.get("auto_open_minutes_after", 15)
    inside_window = (
        scheduled_start is not None
        and schedule_end is not None
        and type(before) is int
        and type(after) is int
        and scheduled_start - timedelta(minutes=before)
        <= now
        <= scheduled_start + timedelta(minutes=after)
        and now < schedule_end
    )
    new_status = "active" if inside_window else "manual_override"
    is_override = new_status == "manual_override"

    attendance_session = AttendanceSession(
        practicum_schedule_id=schedule.id,
        opened_by_user_id=principal.id,
        status=new_status,
        opened_at=now,
        grace_period_minutes=request.grace_period_minutes,
    )
    try:
        session.add(attendance_session)
        session.flush()
        roster = session.execute(
            select(Student.id, Student.student_number, Student.full_name)
            .join(ClassStudent, ClassStudent.student_id == Student.id)
            .where(
                ClassStudent.class_id == schedule.class_id,
                Student.is_active.is_(True),
            )
            .order_by(Student.student_number, Student.id)
        ).all()
        for student_id, student_number, full_name in roster:
            session.add(
                SessionStudent(
                    session_id=attendance_session.id,
                    student_id=student_id,
                    student_number_snapshot=student_number,
                    full_name_snapshot=full_name,
                    snapshot_taken_at=now,
                )
            )
        session.add(
            AuditLog(
                actor_user_id=principal.id,
                action="attendance_session.opened",
                entity_type="attendance_session",
                entity_id=attendance_session.id,
                after_state={
                    "status": new_status,
                    "is_override": is_override,
                    "practicum_schedule_id": str(schedule.id),
                    "grace_period_minutes": request.grace_period_minutes,
                    "roster_count": len(roster),
                },
            )
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiProblem(
            409,
            "session_already_active",
            "Sesi untuk jadwal ini masih terbuka.",
        ) from exc
    session.refresh(attendance_session)
    return _session_response(session, attendance_session)


@router.get(
    "/opening-preference",
    response_model=TeacherOpeningPreferenceResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Read the caller's own session opening mode",
)
def get_opening_preference(
    principal: SessionOperator,
    session: DbSession,
) -> TeacherOpeningPreferenceResponse:
    user = session.get(User, principal.id)
    if user is None:
        raise ApiProblem(404, "user_not_found", "Pengguna tidak ditemukan.")
    return TeacherOpeningPreferenceResponse(
        opening_mode=cast(Literal["manual", "automatic"], user.opening_mode),
        updated_at=as_utc(user.updated_at),
    )


@router.put(
    "/opening-preference",
    response_model=TeacherOpeningPreferenceResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Update the caller's own session opening mode",
)
def put_opening_preference(
    request: TeacherOpeningPreference,
    principal: SessionOperator,
    session: DbSession,
) -> TeacherOpeningPreferenceResponse:
    user = session.get(User, principal.id)
    if user is None:
        raise ApiProblem(404, "user_not_found", "Pengguna tidak ditemukan.")
    before_mode = user.opening_mode
    user.opening_mode = request.opening_mode
    session.add(
        AuditLog(
            actor_user_id=principal.id,
            action="teacher.opening_mode_updated",
            entity_type="user",
            entity_id=user.id,
            before_state={"opening_mode": before_mode},
            after_state={"opening_mode": request.opening_mode},
        )
    )
    session.commit()
    session.refresh(user)
    return TeacherOpeningPreferenceResponse(
        opening_mode=user.opening_mode,
        updated_at=as_utc(user.updated_at),
    )


@router.get(
    "/{session_id}",
    response_model=AttendanceSessionResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Get attendance session status",
)
def get_session(
    session_id: UUID,
    principal: SessionOperator,
    session: DbSession,
) -> AttendanceSessionResponse:
    close_expired_sessions(session, session_id=session_id)
    attendance_session = session.get(AttendanceSession, session_id)
    if attendance_session is None:
        raise ApiProblem(404, "session_not_found", "Sesi presensi tidak ditemukan.")
    schedule = session.get(PracticumSchedule, attendance_session.practicum_schedule_id)
    if schedule is None or not _teacher_scope_allows(principal, schedule):
        raise ApiProblem(404, "session_not_found", "Sesi presensi tidak ditemukan.")
    return _session_response(session, attendance_session)


@router.post(
    "/{session_id}/close",
    response_model=AttendanceSessionResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Close an attendance session",
)
def close_session(
    session_id: UUID,
    principal: SessionOperator,
    session: DbSession,
) -> AttendanceSessionResponse:
    now = datetime.now(UTC)
    close_expired_sessions(session, now=now, session_id=session_id)
    attendance_session = session.get(AttendanceSession, session_id)
    if attendance_session is None:
        raise ApiProblem(404, "session_not_found", "Sesi presensi tidak ditemukan.")
    schedule = session.get(PracticumSchedule, attendance_session.practicum_schedule_id)
    if schedule is None or not _teacher_scope_allows(principal, schedule):
        raise ApiProblem(404, "session_not_found", "Sesi presensi tidak ditemukan.")
    if attendance_session.status in RUNNING_SESSION_STATUSES:
        before_status = attendance_session.status
        attendance_session.status = "closed"
        attendance_session.closed_at = now
        session.add(
            AuditLog(
                actor_user_id=principal.id,
                action="attendance_session.closed",
                entity_type="attendance_session",
                entity_id=attendance_session.id,
                before_state={"status": before_status},
                after_state={"status": "closed", "close_reason": "manual"},
            )
        )
        session.commit()
        session.refresh(attendance_session)
    return _session_response(session, attendance_session)


@router.get(
    "/{session_id}/roster",
    response_model=list[SessionRosterEntry],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List session roster with per-student record status",
)
def get_session_roster(
    session_id: UUID,
    principal: SessionOperator,
    session: DbSession,
) -> list[SessionRosterEntry]:
    close_expired_sessions(session, session_id=session_id)
    attendance_session = session.get(AttendanceSession, session_id)
    if attendance_session is None:
        raise ApiProblem(404, "session_not_found", "Sesi presensi tidak ditemukan.")
    schedule = session.get(PracticumSchedule, attendance_session.practicum_schedule_id)
    if schedule is None or not _teacher_scope_allows(principal, schedule):
        raise ApiProblem(404, "session_not_found", "Sesi presensi tidak ditemukan.")
    rows = session.execute(
        select(
            SessionStudent.student_id,
            SessionStudent.student_number_snapshot,
            SessionStudent.full_name_snapshot,
            AttendanceRecord.status,
        )
        .outerjoin(
            AttendanceRecord,
            (AttendanceRecord.session_id == SessionStudent.session_id)
            & (AttendanceRecord.student_id == SessionStudent.student_id),
        )
        .where(SessionStudent.session_id == attendance_session.id)
        .order_by(SessionStudent.student_number_snapshot, SessionStudent.student_id)
    ).all()
    return [
        SessionRosterEntry(
            student_id=student_id,
            student_number=student_number,
            full_name=full_name,
            record_status=cast(AttendanceStatus | None, record_status),
        )
        for student_id, student_number, full_name, record_status in rows
    ]
