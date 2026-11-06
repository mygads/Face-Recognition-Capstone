"""Public fullscreen display for students (no login, lab + PIN only)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.passwords import verify_password
from presensi_api.api.v1.schemas.common import ApiSchema
from presensi_api.db.models import (
    AttendanceRecord,
    AttendanceSession,
    Laboratory,
    PracticumSchedule,
    SessionStudent,
)
from presensi_api.db.session import get_db_session
from presensi_api.session_lifecycle import as_utc

router = APIRouter(prefix="/public", tags=["public-display"])
DbSession = Annotated[Session, Depends(get_db_session)]


class PublicLaboratory(ApiSchema):
    id: UUID
    code: str
    name: str


class PublicDisplayStudent(ApiSchema):
    student_number: str
    full_name: str
    status: str
    recorded_at: str | None = None


class PublicDisplayResponse(ApiSchema):
    laboratory_id: UUID
    laboratory_name: str
    session_id: UUID | None = None
    subject: str | None = None
    class_name: str | None = None
    status: str | None = None
    opened_at: str | None = None
    present_count: int = 0
    late_count: int = 0
    total_roster: int = 0
    students: list[PublicDisplayStudent] = []


@router.get(
    "/laboratories",
    response_model=list[PublicLaboratory],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List laboratories for public display (no auth)",
)
def list_public_laboratories(session: DbSession) -> list[PublicLaboratory]:
    rows = session.scalars(
        select(Laboratory)
        .where(Laboratory.is_active.is_(True))
        .order_by(Laboratory.code)
    ).all()
    return [PublicLaboratory(id=r.id, code=r.code, name=r.name) for r in rows]


def _check_pin(laboratory: Laboratory, pin: str) -> None:
    if not laboratory.display_pin_hash:
        raise ApiProblem(403, "display_pin_not_set", "PIN layar belum diatur admin.")
    if not verify_password(pin, laboratory.display_pin_hash):
        raise ApiProblem(403, "display_pin_invalid", "PIN salah.")


@router.get(
    "/display",
    response_model=PublicDisplayResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Public display snapshot for a laboratory (lab + PIN)",
)
def get_public_display(
    session: DbSession,
    laboratory_id: UUID,
    pin: Annotated[str, Query(min_length=4, max_length=32)],
) -> PublicDisplayResponse:
    lab = session.get(Laboratory, laboratory_id)
    if lab is None or not lab.is_active:
        raise ApiProblem(404, "laboratory_not_found", "Laboratorium tidak ditemukan.")
    _check_pin(lab, pin)
    sched_ids = session.scalars(
        select(PracticumSchedule.id).where(
            PracticumSchedule.laboratory_id == lab.id,
            PracticumSchedule.is_active.is_(True),
        )
    ).all()
    active = None
    if sched_ids:
        active = session.scalars(
            select(AttendanceSession)
            .where(
                AttendanceSession.practicum_schedule_id.in_(sched_ids),
                AttendanceSession.status.in_(["active", "manual_override"]),
            )
            .order_by(AttendanceSession.opened_at.desc())
            .limit(1)
        ).first()
    if active is None:
        return PublicDisplayResponse(laboratory_id=lab.id, laboratory_name=lab.name)
    schedule = session.get(PracticumSchedule, active.practicum_schedule_id)
    roster = session.execute(
        select(
            SessionStudent.student_number_snapshot,
            SessionStudent.full_name_snapshot,
            AttendanceRecord.status,
            AttendanceRecord.recorded_at,
        )
        .outerjoin(
            AttendanceRecord,
            (AttendanceRecord.session_id == SessionStudent.session_id)
            & (AttendanceRecord.student_id == SessionStudent.student_id),
        )
        .where(SessionStudent.session_id == active.id)
        .order_by(SessionStudent.student_number_snapshot)
    ).all()
    students: list[PublicDisplayStudent] = []
    present = 0
    late = 0
    for number, name, status, recorded_at in roster:
        s = status or "belum"
        if s == "present":
            present += 1
        elif s == "late":
            late += 1
        students.append(
            PublicDisplayStudent(
                student_number=number,
                full_name=name,
                status=s,
                recorded_at=as_utc(recorded_at).isoformat() if recorded_at else None,
            )
        )
    return PublicDisplayResponse(
        laboratory_id=lab.id,
        laboratory_name=lab.name,
        session_id=active.id,
        subject=schedule.subject if schedule else None,
        class_name=None,
        status=active.status,
        opened_at=as_utc(active.opened_at).isoformat(),
        present_count=present,
        late_count=late,
        total_roster=len(students),
        students=students,
    )
