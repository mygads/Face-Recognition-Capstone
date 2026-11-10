"""Public fullscreen display for students (no login, PIN -> short-lived token).

Alur: petugas membuka sesi layar via POST .../session dengan PIN di body
(tidak pernah di URL). Respons berisi token JWT berumur pendek yang dipakai
polling GET berikutnya. PIN salah berulang mengunci sementara (lockout).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.config import AuthSettings
from presensi_api.api.security.dependencies import (
    DISPLAY_PIN_LOCKOUT_MINUTES,
    MAX_DISPLAY_PIN_ATTEMPTS,
    decode_display_token,
    get_auth_settings,
    issue_display_token,
)
from presensi_api.api.security.passwords import verify_password
from presensi_api.api.v1.schemas.common import ApiSchema
from presensi_api.db.models import (
    AttendanceRecord,
    AttendanceSession,
    Device,
    KioskScreen,
    Laboratory,
    PracticumSchedule,
    SessionStudent,
)
from presensi_api.db.session import get_db_session
from presensi_api.session_lifecycle import as_utc

router = APIRouter(prefix="/public", tags=["public-display"])
DbSession = Annotated[Session, Depends(get_db_session)]
AuthDep = Annotated[AuthSettings, Depends(get_auth_settings)]


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


class PublicKioskOption(ApiSchema):
    device_id: UUID
    display_name: str
    camera_label: str | None = None


class LabDisplaySessionRequest(ApiSchema):
    laboratory_id: UUID
    pin: str


class KioskDisplaySessionRequest(ApiSchema):
    device_id: UUID
    pin: str


class DisplaySessionResponse(ApiSchema):
    display_token: str
    expires_in_seconds: int
    snapshot: PublicDisplayResponse


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


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _ensure_not_locked(fail_count: int, locked_until: datetime | None) -> None:
    if locked_until is not None and datetime.now(UTC) < _as_aware(locked_until):
        raise ApiProblem(
            429, "display_pin_locked", "Terlalu banyak PIN salah. Coba lagi nanti."
        )


def _register_pin_failure(fail_count: int) -> tuple[int, datetime | None]:
    fail_count += 1
    locked_until: datetime | None = None
    if fail_count >= MAX_DISPLAY_PIN_ATTEMPTS:
        locked_until = datetime.now(UTC) + timedelta(
            minutes=DISPLAY_PIN_LOCKOUT_MINUTES
        )
        fail_count = 0
    return fail_count, locked_until


def _check_lab_pin(lab: Laboratory, pin: str) -> None:
    if not lab.display_pin_hash:
        raise ApiProblem(403, "display_pin_not_set", "PIN layar belum diatur admin.")
    _ensure_not_locked(lab.display_pin_fail_count or 0, lab.display_pin_locked_until)
    if not verify_password(pin, lab.display_pin_hash):
        lab.display_pin_fail_count, lab.display_pin_locked_until = (
            _register_pin_failure(lab.display_pin_fail_count or 0)
        )
        raise ApiProblem(403, "display_pin_invalid", "PIN salah.")
    lab.display_pin_fail_count = 0
    lab.display_pin_locked_until = None


def _check_kiosk_pin(kiosk: KioskScreen, pin: str) -> None:
    if not kiosk.pin_hash:
        raise ApiProblem(403, "display_pin_not_set", "PIN layar belum diatur admin.")
    _ensure_not_locked(kiosk.pin_fail_count or 0, kiosk.pin_locked_until)
    if not verify_password(pin, kiosk.pin_hash):
        kiosk.pin_fail_count, kiosk.pin_locked_until = _register_pin_failure(
            kiosk.pin_fail_count or 0
        )
        raise ApiProblem(403, "display_pin_invalid", "PIN salah.")
    kiosk.pin_fail_count = 0
    kiosk.pin_locked_until = None


def _build_snapshot(lab: Laboratory, session: Session) -> PublicDisplayResponse:
    sched_ids = session.scalars(
        select(PracticumSchedule.id).where(
            PracticumSchedule.laboratory_id == lab.id,
            PracticumSchedule.is_active.is_(True),
        )
    ).all()
    active = None
    if sched_ids:
        candidates = session.scalars(
            select(AttendanceSession)
            .where(
                AttendanceSession.practicum_schedule_id.in_(sched_ids),
                AttendanceSession.status.in_(["active", "manual_override"]),
            )
            .order_by(AttendanceSession.opened_at.desc())
            .limit(2)
        ).all()
        # Satu sesi cocok -> siap; nol/lebih dari satu -> belum siap.
        if len(candidates) == 1:
            active = candidates[0]
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


@router.post(
    "/display/session",
    response_model=DisplaySessionResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Open a lab display session with PIN (body, no login)",
)
def open_lab_display_session(
    request: LabDisplaySessionRequest,
    session: DbSession,
    settings: AuthDep,
) -> DisplaySessionResponse:
    lab = session.get(Laboratory, request.laboratory_id)
    if lab is None or not lab.is_active:
        raise ApiProblem(404, "laboratory_not_found", "Laboratorium tidak ditemukan.")
    try:
        _check_lab_pin(lab, request.pin)
    except ApiProblem:
        session.commit()
        raise
    session.commit()
    token, ttl = issue_display_token("lab", lab.id, lab.id, settings)
    return DisplaySessionResponse(
        display_token=token,
        expires_in_seconds=ttl,
        snapshot=_build_snapshot(lab, session),
    )


@router.get(
    "/display",
    response_model=PublicDisplayResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Public display snapshot (short-lived token, no login)",
)
def get_public_display(
    session: DbSession,
    settings: AuthDep,
    token: Annotated[str, Query(min_length=16, max_length=1024)],
) -> PublicDisplayResponse:
    claims = decode_display_token(token, settings)
    if claims is None or claims.kind != "lab":
        raise ApiProblem(401, "display_token_invalid", "Sesi layar tidak valid.")
    lab = session.get(Laboratory, claims.laboratory_id)
    if lab is None or not lab.is_active:
        raise ApiProblem(404, "laboratory_not_found", "Laboratorium tidak ditemukan.")
    return _build_snapshot(lab, session)


@router.post(
    "/kiosk-display/session",
    response_model=DisplaySessionResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Open a kiosk display session with PIN (body, no login)",
)
def open_kiosk_display_session(
    request: KioskDisplaySessionRequest,
    session: DbSession,
    settings: AuthDep,
) -> DisplaySessionResponse:
    device = session.get(Device, request.device_id)
    if device is None or not device.is_active:
        raise ApiProblem(404, "device_not_found", "Perangkat tidak ditemukan.")
    kiosk = session.scalar(
        select(KioskScreen).where(
            KioskScreen.device_id == device.id,
            KioskScreen.laboratory_id == device.laboratory_id,
            KioskScreen.is_active.is_(True),
        )
    )
    lab = session.get(Laboratory, device.laboratory_id)
    if lab is None or not lab.is_active:
        raise ApiProblem(404, "laboratory_not_found", "Laboratorium tidak ditemukan.")
    if kiosk is None:
        raise ApiProblem(404, "kiosk_not_found", "Layar kiosk tidak terdaftar.")
    try:
        _check_kiosk_pin(kiosk, request.pin)
    except ApiProblem:
        session.commit()
        raise
    kiosk.last_seen_at = datetime.now(UTC)
    session.commit()
    token, ttl = issue_display_token("kiosk", device.id, lab.id, settings)
    return DisplaySessionResponse(
        display_token=token,
        expires_in_seconds=ttl,
        snapshot=_build_snapshot(lab, session),
    )


@router.get(
    "/kiosk-display",
    response_model=PublicDisplayResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Public kiosk snapshot (short-lived token, no login)",
)
def get_kiosk_display(
    session: DbSession,
    settings: AuthDep,
    token: Annotated[str, Query(min_length=16, max_length=1024)],
) -> PublicDisplayResponse:
    claims = decode_display_token(token, settings)
    if claims is None or claims.kind != "kiosk":
        raise ApiProblem(401, "display_token_invalid", "Sesi layar tidak valid.")
    device = session.get(Device, claims.subject_id)
    if device is None or not device.is_active:
        raise ApiProblem(404, "device_not_found", "Perangkat tidak ditemukan.")
    kiosk = session.scalar(
        select(KioskScreen).where(
            KioskScreen.device_id == device.id,
            KioskScreen.laboratory_id == device.laboratory_id,
            KioskScreen.is_active.is_(True),
        )
    )
    if kiosk is None:
        raise ApiProblem(404, "kiosk_not_found", "Layar kiosk tidak terdaftar.")
    if kiosk.pin_locked_until is not None and datetime.now(UTC) < _as_aware(
        kiosk.pin_locked_until
    ):
        raise ApiProblem(429, "display_pin_locked", "Layar dikunci sementara.")
    lab = session.get(Laboratory, device.laboratory_id)
    if lab is None or not lab.is_active:
        raise ApiProblem(404, "laboratory_not_found", "Laboratorium tidak ditemukan.")
    if claims.laboratory_id != lab.id:
        raise ApiProblem(401, "display_token_invalid", "Sesi layar tidak valid.")
    return _build_snapshot(lab, session)


@router.get(
    "/kiosk-screens",
    response_model=list[PublicKioskOption],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List active kiosk screens for a laboratory (no login)",
)
def list_public_kiosk_screens(
    session: DbSession,
    laboratory_id: UUID,
) -> list[PublicKioskOption]:
    rows = session.scalars(
        select(KioskScreen).where(
            KioskScreen.laboratory_id == laboratory_id,
            KioskScreen.is_active.is_(True),
        )
    ).all()
    return [
        PublicKioskOption(
            device_id=r.device_id,
            display_name=r.display_name,
            camera_label=r.camera_label,
        )
        for r in rows
    ]
