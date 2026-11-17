"""Teacher-driven manual attendance marks (fail-closed operational path)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from presensi_api.api.errors import ApiProblem
from presensi_api.api.security.roles import (
    AuthenticatedUser,
    Permission,
    RoleCode,
)
from presensi_api.api.v1.schemas.attendance import ManualMarkRequest
from presensi_api.db.models import (
    AttendanceRecord,
    AttendanceSession,
    AuditLog,
    PracticumSchedule,
    SessionStudent,
    Student,
)
from presensi_api.display_notify import (
    notify_display_changed,
    pg_notify_display_changed,
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
    session_running = attendance_session.status in RUNNING_SESSION_STATUSES
    session_closed = attendance_session.status == "closed"
    session_cancelled = attendance_session.status == "cancelled"
    if RoleCode.ADMIN not in principal.roles:
        from presensi_api.api.security.roles import Permission as _Perm
        from presensi_api.api.security.scope import (
            laborant_lab_ids as _mll,
        )
        from presensi_api.api.security.scope import (
            teacher_class_ids as _mtc,
        )

        # Otorisasi dibedakan per status sesi (state-aware):
        # - sesi berjalan -> butuh izin tandai manual + cakupan;
        # - sesi closed -> butuh izin koreksi sesi tertutup + cakupan
        #   (TANPA mensyaratkan izin tandai manual);
        # - sesi cancelled -> tidak dapat ditulis lewat jalur ini.
        _ok = False
        if session_closed or session_cancelled:
            if RoleCode.TEACHER in principal.roles:
                # MVP 1:1: guru jadwal atau guru mana pun yang ditugaskan
                # di kelas tersebut boleh mengoreksi (termasuk pengganti).
                if schedule.teacher_user_id == principal.id:
                    _ok = True
                elif schedule.class_id in _mtc(db, principal.id):
                    _ok = True
            elif RoleCode.LABORANT in principal.roles:
                if _Perm.ATTENDANCE_CORRECT_CLOSED in principal.permissions and (
                    schedule.laboratory_id in _mll(db, principal.id)
                ):
                    _ok = True
        elif session_running:
            if RoleCode.TEACHER in principal.roles:
                if _Perm.ATTENDANCE_MANUAL not in principal.permissions:
                    _ok = False
                elif schedule.teacher_user_id == principal.id:
                    _ok = True
                elif schedule.class_id in _mtc(db, principal.id):
                    _ok = True
            elif RoleCode.LABORANT in principal.roles:
                if _Perm.ATTENDANCE_MANUAL in principal.permissions and (
                    schedule.laboratory_id in _mll(db, principal.id)
                ):
                    _ok = True
        if not _ok:
            raise ApiProblem(404, "session_not_found", "Sesi presensi tidak ditemukan.")
    if session_cancelled:
        # Sesi yang dibatalkan berarti praktikum tidak dilaksanakan:
        # tolak untuk semua role (termasuk pemegang izin koreksi/admin)
        # agar tidak tercipta catatan kehadiran pada sesi batal.
        raise ApiProblem(
            409,
            "session_inactive",
            "Sesi presensi dibatalkan dan tidak dapat dikoreksi. "
            "Buat jadwal pengganti bila praktikum tetap dilaksanakan.",
        )
    if (
        session_closed
        and Permission.ATTENDANCE_CORRECT_CLOSED not in principal.permissions
    ):
        # Sesi tertutup hanya bisa dikoreksi lewat izin terpisah
        # (koreksi pascasesi): alasan wajib dan tercatat pada audit log.
        # Validasi ini TIDAK dikendurkan agar kontrak 409 lama tetap berlaku.
        raise ApiProblem(
            409,
            "session_inactive",
            "Sesi presensi sudah ditutup. "
            "Koreksi pascasesi memerlukan izin koreksi sesi tertutup.",
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
    note = request.note.strip() if request.note else None
    occurred = request.occurred_at if request.occurred_at is not None else None
    if existing is None and session_closed and not note:
        # Catatan baru pada sesi tertutup adalah koreksi pascasesi:
        # alasan wajib agar dapat diaudit (aturan sama seperti pembaruan).
        raise ApiProblem(
            422,
            "reason_required",
            "Alasan perubahan wajib diisi untuk koreksi sesi tertutup.",
        )
    if existing is not None:
        # Pengganti alur koreksi: guru/aslab berwenang langsung memperbarui
        # catatan (termasuk milik face recognition) tanpa persetujuan admin.
        # Alasan wajib: tanpa note, perubahan tidak dapat diaudit.
        if not note:
            raise ApiProblem(
                422,
                "reason_required",
                "Alasan perubahan wajib diisi saat memperbarui catatan.",
            )
        before = {
            "status": existing.status,
            "source": existing.source,
            "recognition_event_id": (
                str(existing.recognition_event_id)
                if existing.recognition_event_id is not None
                else None
            ),
            "note": existing.note,
            "occurred_at": (
                as_utc(existing.occurred_at).isoformat()
                if existing.occurred_at is not None
                else None
            ),
        }
        # Provenance: keputusan akhir di tangan manusia -> sumber menjadi
        # manual dan tautan event DILEPAS (kontrak CHECK: manual -> event
        # NULL; baris event AI asli tidak berubah/immutable dan tetap
        # diaudit via before_state). Replay event (retry edge) tetap
        # idempoten lewat fallback sesi+siswa di attendance_decision.
        existing.status = request.status
        existing.source = "manual"
        existing.recognition_event_id = None
        existing.note = note
        if request.occurred_at is not None:
            existing.occurred_at = request.occurred_at
        existing.recorded_by_user_id = principal.id
        existing.recorded_at = datetime.now(UTC)
        db.add(
            AuditLog(
                actor_user_id=principal.id,
                action="attendance.manual_updated",
                entity_type="attendance_record",
                entity_id=existing.id,
                before_state={
                    "session_id": str(attendance_session.id),
                    "student_id": str(request.student_id),
                    "session_status": attendance_session.status,
                    **before,
                },
                after_state={
                    "status": request.status,
                    "source": "manual",
                    "recognition_event_id": None,
                    "note": note,
                    "recorded_by_user_id": str(principal.id),
                    "recorded_at": as_utc(existing.recorded_at).isoformat(),
                },
            )
        )
        pg_notify_display_changed(db, schedule.laboratory_id)
        db.commit()
        db.refresh(existing)
        notify_display_changed()
        return existing
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
                occurred_at=occurred,
                rule_version=attendance_session.grace_period_minutes,
                note=note,
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
                "session_status": attendance_session.status,
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
    pg_notify_display_changed(db, schedule.laboratory_id)
    db.commit()
    db.refresh(record)
    notify_display_changed()
    return record
