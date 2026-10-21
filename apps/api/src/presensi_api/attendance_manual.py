"""Teacher-driven manual attendance marks (fail-closed operational path)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from presensi_api.api.errors import ApiProblem
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
from presensi_api.api.v1.schemas.attendance import ManualMarkRequest
from presensi_api.db.models import (
    AttendanceRecord,
    AttendanceSession,
    AuditLog,
    PracticumSchedule,
    SessionStudent,
    Student,
)
from presensi_api.session_lifecycle import (
    RUNNING_SESSION_STATUSES,
    as_utc,
    close_expired_sessions,
)


def mark_manual_attendance(
    db: Session,
    session_id: object,
    request: ManualMarkRequest,
    principal: AuthenticatedUser,
) -> AttendanceRecord:
    """Record one teacher-chosen attendance status for a roster member."""
    close_expired_sessions(db, session_id=session_id)  # type: ignore[arg-type]
    attendance_session = db.scalar(
        select(AttendanceSession)
        .where(AttendanceSession.id == session_id)
        .with_for_update()
    )
    if attendance_session is None:
        raise ApiProblem(404, "session_not_found", "Sesi presensi tidak ditemukan.")
    schedule = db.get(PracticumSchedule, attendance_session.practicum_schedule_id)
    if schedule is None:
        raise ApiProblem(404, "session_not_found", "Sesi presensi tidak ditemukan.")
    if (
        RoleCode.TEACHER in principal.roles
        and RoleCode.ADMIN not in principal.roles
        and schedule.teacher_user_id != principal.id
    ):
        raise ApiProblem(404, "session_not_found", "Sesi presensi tidak ditemukan.")
    if attendance_session.status not in RUNNING_SESSION_STATUSES:
        raise ApiProblem(
            409, "session_inactive", "Sesi presensi sudah ditutup atau dibatalkan."
        )

    student = db.get(Student, request.student_id)
    if student is None:
        raise ApiProblem(404, "student_not_found", "Siswa tidak ditemukan.")
    roster_entry = db.get(
        SessionStudent,
        {"session_id": attendance_session.id, "student_id": request.student_id},
    )
    if roster_entry is None:
        raise ApiProblem(
            404,
            "student_not_in_session_roster",
            "Siswa tidak termasuk dalam roster sesi ini.",
        )

    existing = db.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.session_id == attendance_session.id,
            AttendanceRecord.student_id == request.student_id,
        )
    )
    if existing is not None:
        raise ApiProblem(
            409,
            "attendance_already_recorded",
            "Presensi siswa untuk sesi ini sudah tercatat.",
        )

    note = request.note.strip() if request.note else None
    record: AttendanceRecord | None = None
    try:
        # A concurrent mark (manual or recognition) can pass the pre-check
        # above; the savepoint keeps the UNIQUE(session_id, student_id)
        # violation from aborting the surrounding unit of work.
        with db.begin_nested():
            record = AttendanceRecord(
                session_id=attendance_session.id,
                student_id=request.student_id,
                recognition_event_id=None,
                recorded_by_user_id=principal.id,
                status=request.status,
                source="manual",
                recorded_at=datetime.now(UTC),
            )
            db.add(record)
            db.flush()
    except IntegrityError as exc:
        raise ApiProblem(
            409,
            "attendance_already_recorded",
            "Presensi siswa untuk sesi ini sudah tercatat.",
        ) from exc
    assert record is not None
    db.add(
        AuditLog(
            actor_user_id=principal.id,
            action="attendance.manual_marked",
            entity_type="attendance_record",
            entity_id=record.id,
            before_state={
                "session_id": str(attendance_session.id),
                "student_id": str(request.student_id),
                "student_number_snapshot": roster_entry.student_number_snapshot,
                "full_name_snapshot": roster_entry.full_name_snapshot,
            },
            after_state={
                "status": request.status,
                "source": "manual",
                "recorded_by_user_id": str(principal.id),
                "note": note,
                "recorded_at": as_utc(record.recorded_at).isoformat(),
            },
        )
    )
    db.commit()
    db.refresh(record)
    return record
