from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from presensi_api.db.models import (
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


def as_utc(value: datetime) -> datetime:
    """Normalize a database timestamp, including SQLite's naive test values."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def scheduled_end_at(schedule: PracticumSchedule, opened_at: datetime) -> datetime:
    timezone = ZoneInfo(schedule.timezone_name)
    local_opened_at = as_utc(opened_at).astimezone(timezone)
    return datetime.combine(
        local_opened_at.date(), schedule.end_time, tzinfo=timezone
    ).astimezone(UTC)


def scheduled_start_at(schedule: PracticumSchedule, reference_at: datetime) -> datetime:
    timezone = ZoneInfo(schedule.timezone_name)
    local_reference = as_utc(reference_at).astimezone(timezone)
    return datetime.combine(
        local_reference.date(), schedule.start_time, tzinfo=timezone
    ).astimezone(UTC)


def session_can_open_today(
    schedule: PracticumSchedule, now: datetime
) -> tuple[bool, str | None]:
    local_now = as_utc(now).astimezone(ZoneInfo(schedule.timezone_name))
    if local_now.weekday() != schedule.weekday:
        return False, "Jadwal ini tidak berlaku pada hari ini."
    if local_now.date() < schedule.effective_from or (
        schedule.effective_through is not None
        and local_now.date() > schedule.effective_through
    ):
        return False, "Jadwal tidak berlaku pada tanggal ini."
    if local_now.time().replace(tzinfo=None) >= schedule.end_time:
        return False, "Waktu jadwal sudah berakhir."
    return True, None


def close_expired_sessions(
    session: Session,
    *,
    now: datetime | None = None,
    session_id: UUID | None = None,
) -> int:
    """Close active sessions at their recurring schedule's local end time."""
    current_time = as_utc(now or datetime.now(UTC))
    query = select(AttendanceSession).where(AttendanceSession.status == "active")
    if session_id is not None:
        query = query.where(AttendanceSession.id == session_id)
    active_sessions = session.scalars(query).all()
    closed_count = 0
    for attendance_session in active_sessions:
        schedule = session.get(
            PracticumSchedule, attendance_session.practicum_schedule_id
        )
        if schedule is None:
            continue
        try:
            session_end = scheduled_end_at(schedule, attendance_session.opened_at)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            continue
        if session_end <= current_time:
            result = session.execute(
                update(AttendanceSession)
                .where(
                    AttendanceSession.id == attendance_session.id,
                    AttendanceSession.status == "active",
                )
                .values(status="closed", closed_at=session_end)
                .returning(AttendanceSession.id)
            )
            if result.scalar_one_or_none() is None:
                continue
            session.add(
                AuditLog(
                    actor_user_id=None,
                    action="attendance_session.closed_automatically",
                    entity_type="attendance_session",
                    entity_id=attendance_session.id,
                    before_state={"status": "active"},
                    after_state={
                        "status": "closed",
                        "close_reason": "schedule_end_time",
                    },
                )
            )
            closed_count += 1
    if closed_count:
        session.commit()
    return closed_count


def auto_open_due_sessions(
    session: Session,
    *,
    policy: dict[str, object],
    now: datetime | None = None,
) -> int:
    """Open due schedules in automatic mode using the same roster snapshot rules."""
    if policy.get("mode") != "automatic":
        return 0
    before = policy.get("auto_open_minutes_before", 0)
    after = policy.get("auto_open_minutes_after", 15)
    grace = policy.get("default_grace_period_minutes", 15)
    if (
        type(before) is not int
        or not 0 <= before <= 15
        or type(after) is not int
        or not 0 <= after <= 15
        or type(grace) is not int
        or not 0 <= grace <= 1440
    ):
        return 0

    current_time = as_utc(now or datetime.now(UTC))
    schedules = session.scalars(
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
    ).all()
    active_schedule_ids = set(
        session.scalars(
            select(AttendanceSession.practicum_schedule_id).where(
                AttendanceSession.status == "active"
            )
        ).all()
    )
    created_count = 0
    for schedule in schedules:
        if schedule.id in active_schedule_ids:
            continue
        try:
            timezone = ZoneInfo(schedule.timezone_name)
            local_now = current_time.astimezone(timezone)
            if (
                local_now.weekday() != schedule.weekday
                or local_now.date() < schedule.effective_from
                or (
                    schedule.effective_through is not None
                    and local_now.date() > schedule.effective_through
                )
            ):
                continue
            scheduled_start = datetime.combine(
                local_now.date(), schedule.start_time, tzinfo=timezone
            ).astimezone(UTC)
            schedule_end = datetime.combine(
                local_now.date(), schedule.end_time, tzinfo=timezone
            ).astimezone(UTC)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            continue
        if not (
            scheduled_start - timedelta(minutes=before)
            <= current_time
            <= scheduled_start + timedelta(minutes=after)
            and current_time < schedule_end
        ):
            continue
        roster = session.execute(
            select(Student.id, Student.student_number, Student.full_name)
            .join(ClassStudent, ClassStudent.student_id == Student.id)
            .where(
                ClassStudent.class_id == schedule.class_id,
                Student.is_active.is_(True),
            )
            .order_by(Student.student_number, Student.id)
        ).all()
        if not roster:
            continue
        try:
            with session.begin_nested():
                attendance_session = AttendanceSession(
                    practicum_schedule_id=schedule.id,
                    opened_by_user_id=None,
                    status="active",
                    opened_at=current_time,
                    grace_period_minutes=grace,
                )
                session.add(attendance_session)
                session.flush()
                for student_id, student_number, full_name in roster:
                    session.add(
                        SessionStudent(
                            session_id=attendance_session.id,
                            student_id=student_id,
                            student_number_snapshot=student_number,
                            full_name_snapshot=full_name,
                            snapshot_taken_at=current_time,
                        )
                    )
                session.add(
                    AuditLog(
                        actor_user_id=None,
                        action="attendance_session.opened_automatically",
                        entity_type="attendance_session",
                        entity_id=attendance_session.id,
                        after_state={
                            "status": "active",
                            "practicum_schedule_id": str(schedule.id),
                            "grace_period_minutes": grace,
                            "roster_count": len(roster),
                            "open_window_before_minutes": before,
                            "open_window_after_minutes": after,
                        },
                    )
                )
                session.flush()
            active_schedule_ids.add(schedule.id)
            created_count += 1
        except IntegrityError:
            # Another API worker may have opened this schedule at the same time.
            continue
    if created_count:
        session.commit()
    return created_count
