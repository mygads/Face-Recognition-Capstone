"""Cakupan data per role: penugasan guru-kelas dan laboran-lab."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from presensi_api.api.errors import ApiProblem
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
from presensi_api.db.models import (
    AttendanceSession,
    ClassLaboratory,
    ClassStudent,
    LaborantLabAssignment,
    PracticumSchedule,
    SessionStudent,
    TeacherClassAssignment,
)


def is_admin(principal: AuthenticatedUser) -> bool:
    return RoleCode.ADMIN in principal.roles


def teacher_class_ids(
    session: Session, user_id: UUID, on: date | None = None
) -> set[UUID]:
    on = on or date.today()
    rows = session.scalars(
        select(TeacherClassAssignment).where(TeacherClassAssignment.user_id == user_id)
    ).all()
    out: set[UUID] = set()
    for row in rows:
        if row.starts_on is not None and row.starts_on > on:
            continue
        if row.ends_on is not None and row.ends_on < on:
            continue
        out.add(row.class_id)
    return out


def laborant_lab_ids(session: Session, user_id: UUID) -> set[UUID]:
    rows = session.scalars(
        select(LaborantLabAssignment.laboratory_id).where(
            LaborantLabAssignment.user_id == user_id
        )
    ).all()
    return set(rows)


def is_substitute_teacher(
    session: Session, user_id: UUID, class_id: UUID, on: date | None = None
) -> bool:
    on = on or date.today()
    row = session.get(TeacherClassAssignment, (user_id, class_id))
    if row is None or not row.is_substitute:
        return False
    if row.starts_on is not None and row.starts_on > on:
        return False
    if row.ends_on is not None and row.ends_on < on:
        return False
    return True


def schedule_read_allowed(
    session: Session, principal: AuthenticatedUser, schedule: PracticumSchedule
) -> bool:
    if is_admin(principal):
        return True
    if RoleCode.TEACHER in principal.roles:
        classes = teacher_class_ids(session, principal.id)
        if schedule.class_id in classes:
            return True
        # Kompatibilitas historis: jadwal lama menunjuk guru langsung.
        if schedule.teacher_user_id == principal.id:
            return True
    if RoleCode.LABORANT in principal.roles:
        from presensi_api.api.security.roles import Permission

        if Permission.SCHEDULE_READ in principal.permissions:
            labs = laborant_lab_ids(session, principal.id)
            if schedule.laboratory_id in labs:
                return True
    return False


def schedule_operate_allowed(
    session: Session, principal: AuthenticatedUser, schedule: PracticumSchedule
) -> bool:
    if is_admin(principal):
        return True
    if RoleCode.TEACHER in principal.roles:
        if schedule.teacher_user_id == principal.id:
            return True
        if is_substitute_teacher(session, principal.id, schedule.class_id):
            return True
    if RoleCode.LABORANT in principal.roles:
        from presensi_api.api.security.roles import Permission

        if Permission.SESSION_OPERATE in principal.permissions:
            labs = laborant_lab_ids(session, principal.id)
            if schedule.laboratory_id in labs:
                return True
    return False


def ensure_schedule_read(
    session: Session, principal: AuthenticatedUser, schedule: PracticumSchedule
) -> None:
    if not schedule_read_allowed(session, principal, schedule):
        raise ApiProblem(404, "schedule_not_found", "Jadwal tidak ditemukan.")


def ensure_schedule_operate(
    session: Session, principal: AuthenticatedUser, schedule: PracticumSchedule
) -> None:
    if not schedule_operate_allowed(session, principal, schedule):
        raise ApiProblem(404, "schedule_not_found", "Jadwal tidak ditemukan.")


def class_ids_in_laborant_scope(
    session: Session, principal: AuthenticatedUser
) -> set[UUID]:
    labs = laborant_lab_ids(session, principal.id)
    if not labs:
        return set()
    rows = session.scalars(
        select(ClassLaboratory.class_id).where(ClassLaboratory.laboratory_id.in_(labs))
    ).all()
    return set(rows)


def session_read_allowed(
    session: Session, principal: AuthenticatedUser, schedule: PracticumSchedule
) -> bool:
    from presensi_api.api.security.roles import Permission

    if is_admin(principal):
        return True
    if RoleCode.TEACHER in principal.roles:
        classes = teacher_class_ids(session, principal.id)
        if schedule.class_id in classes:
            return True
        if schedule.teacher_user_id == principal.id:
            return True
    if RoleCode.LABORANT in principal.roles:
        if Permission.SESSION_VIEW in principal.permissions:
            labs = laborant_lab_ids(session, principal.id)
            if schedule.laboratory_id in labs:
                return True
    return False


def _student_in_classes(
    session: Session, student_id: UUID, class_ids: set[UUID]
) -> bool:
    """Siswa terdaftar sebagai anggota salah satu kelas dalam cakupan."""
    hit = session.scalar(
        select(ClassStudent.student_id).where(
            ClassStudent.student_id == student_id,
            ClassStudent.class_id.in_(class_ids),
        )
    )
    return hit is not None


def class_read_allowed(
    session: Session, principal: AuthenticatedUser, class_id: UUID
) -> bool:
    """Kelas boleh dibaca: admin selalu; guru via penugasan; laboran via kelas-lab."""
    if is_admin(principal):
        return True
    if RoleCode.TEACHER in principal.roles:
        if class_id in teacher_class_ids(session, principal.id):
            return True
    if RoleCode.LABORANT in principal.roles:
        if class_id in class_ids_in_laborant_scope(session, principal):
            return True
    return False


def ensure_class_read(
    session: Session, principal: AuthenticatedUser, class_id: UUID
) -> None:
    if not class_read_allowed(session, principal, class_id):
        raise ApiProblem(404, "class_not_found", "Kelas tidak ditemukan.")


def student_read_allowed(
    session: Session, principal: AuthenticatedUser, student_id: UUID
) -> bool:
    """True bila siswa berada dalam cakupan pembaca (aturan sama dengan laporan/EWS).

    Guru: kelas penugasan ATAU roster sesi yang jadwalnya milik guru tersebut.
    Laboran: roster sesi pada lab penugasan. Admin: selalu True.
    Objek di luar cakupan diperlakukan tidak ada (404) oleh pemanggil.
    """
    if is_admin(principal):
        return True
    if RoleCode.TEACHER in principal.roles:
        classes = teacher_class_ids(session, principal.id)
        if classes and _student_in_classes(session, student_id, classes):
            return True
        owned = session.scalar(
            select(SessionStudent.student_id)
            .join(
                AttendanceSession,
                AttendanceSession.id == SessionStudent.session_id,
            )
            .join(
                PracticumSchedule,
                PracticumSchedule.id == AttendanceSession.practicum_schedule_id,
            )
            .where(
                SessionStudent.student_id == student_id,
                PracticumSchedule.teacher_user_id == principal.id,
            )
        )
        if owned is not None:
            return True
    if RoleCode.LABORANT in principal.roles:
        scope_classes = class_ids_in_laborant_scope(session, principal)
        if scope_classes and _student_in_classes(session, student_id, scope_classes):
            return True
    if RoleCode.LABORANT in principal.roles:
        labs = laborant_lab_ids(session, principal.id)
        if labs:
            hit = session.scalar(
                select(SessionStudent.student_id)
                .join(
                    AttendanceSession,
                    AttendanceSession.id == SessionStudent.session_id,
                )
                .join(
                    PracticumSchedule,
                    PracticumSchedule.id == AttendanceSession.practicum_schedule_id,
                )
                .where(
                    SessionStudent.student_id == student_id,
                    PracticumSchedule.laboratory_id.in_(labs),
                )
            )
            if hit is not None:
                return True
    return False


def ensure_student_read(
    session: Session, principal: AuthenticatedUser, student_id: UUID
) -> None:
    if not student_read_allowed(session, principal, student_id):
        raise ApiProblem(404, "student_not_found", "Siswa tidak ditemukan.")


def ensure_session_read(
    session: Session, principal: AuthenticatedUser, schedule: PracticumSchedule
) -> None:
    if not session_read_allowed(session, principal, schedule):
        raise ApiProblem(404, "session_not_found", "Sesi presensi tidak ditemukan.")
