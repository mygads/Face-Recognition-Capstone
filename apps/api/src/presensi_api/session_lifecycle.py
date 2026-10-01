from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from presensi_api.db.models import AttendanceSession, AuditLog, PracticumSchedule


def as_utc(value: datetime) -> datetime:
    """Normalize a database timestamp, including SQLite's naive test values."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def scheduled_end_at(schedule: PracticumSchedule, opened_at: datetime) -> datetime:
    timezone = ZoneInfo(schedule.timezone_name)
    local_opened_at = as_utc(opened_at).astimezone(timezone)
    return datetime.combine(
        local_opened_at.date(), schedule.end_time, tzinfo=timezone
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
