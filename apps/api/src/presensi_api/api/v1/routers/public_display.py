"""Public fullscreen display for students (no login, PIN -> short-lived token).

Alur: petugas membuka sesi layar via POST .../session dengan PIN di body
(tidak pernah di URL). Respons berisi token JWT berumur pendek yang dipakai
polling GET berikutnya. PIN salah berulang mengunci sementara (lockout).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy import func, select
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
from presensi_api.db.session import get_db_session, get_session_factory
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


class KioskSpotlight(ApiSchema):
    full_name: str
    status: str
    recorded_at: str | None = None


class KioskLiveUpdate(ApiSchema):
    """Payload ringan stream SSE kiosk: agregat + 1 sorotan, TANPA roster."""

    laboratory_id: UUID
    laboratory_name: str
    session_id: UUID | None = None
    subject: str | None = None
    status: str | None = None
    opened_at: str | None = None
    present_count: int = 0
    late_count: int = 0
    waiting_count: int = 0
    total_roster: int = 0
    spotlight: KioskSpotlight | None = None
    server_time: str


class PublicKioskOption(ApiSchema):
    device_id: UUID
    display_name: str
    camera_label: str | None = None


class LabDisplaySessionRequest(ApiSchema):
    laboratory_id: UUID
    pin: str
    light: bool = False


class KioskDisplaySessionRequest(ApiSchema):
    device_id: UUID
    pin: str
    light: bool = False


class DisplaySessionResponse(ApiSchema):
    display_token: str
    expires_in_seconds: int
    snapshot: PublicDisplayResponse


class DisplayRotateRequest(ApiSchema):
    display_token: str = Field(min_length=16, max_length=1024)


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


def _find_active_session(lab: Laboratory, session: Session) -> AttendanceSession | None:
    sched_ids = session.scalars(
        select(PracticumSchedule.id).where(
            PracticumSchedule.laboratory_id == lab.id,
            PracticumSchedule.is_active.is_(True),
        )
    ).all()
    if not sched_ids:
        return None
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
        return candidates[0]
    return None


def _build_live_update(lab: Laboratory, session: Session) -> KioskLiveUpdate:
    """Agregat ringan untuk SSE: hitungan + 1 hasil terbaru, tanpa roster."""
    active = _find_active_session(lab, session)
    if active is None:
        return KioskLiveUpdate(
            laboratory_id=lab.id,
            laboratory_name=lab.name,
            server_time=datetime.now(UTC).isoformat(),
        )
    schedule = session.get(PracticumSchedule, active.practicum_schedule_id)
    total = (
        session.scalar(
            select(func.count())
            .select_from(SessionStudent)
            .where(SessionStudent.session_id == active.id)
        )
        or 0
    )
    present = (
        session.scalar(
            select(func.count())
            .select_from(AttendanceRecord)
            .where(
                AttendanceRecord.session_id == active.id,
                AttendanceRecord.status == "present",
            )
        )
        or 0
    )
    late = (
        session.scalar(
            select(func.count())
            .select_from(AttendanceRecord)
            .where(
                AttendanceRecord.session_id == active.id,
                AttendanceRecord.status == "late",
            )
        )
        or 0
    )
    latest = session.execute(
        select(
            SessionStudent.full_name_snapshot,
            AttendanceRecord.status,
            AttendanceRecord.recorded_at,
        )
        .join(
            AttendanceRecord,
            (AttendanceRecord.session_id == SessionStudent.session_id)
            & (AttendanceRecord.student_id == SessionStudent.student_id),
        )
        .where(
            SessionStudent.session_id == active.id,
            AttendanceRecord.status.in_(["present", "late"]),
        )
        .order_by(AttendanceRecord.recorded_at.desc())
        .limit(1)
    ).first()
    spotlight: KioskSpotlight | None = None
    if latest is not None:
        name, status, recorded_at = latest
        spotlight = KioskSpotlight(
            full_name=name,
            status=status,
            recorded_at=as_utc(recorded_at).isoformat() if recorded_at else None,
        )
    return KioskLiveUpdate(
        laboratory_id=lab.id,
        laboratory_name=lab.name,
        session_id=active.id,
        subject=schedule.subject if schedule else None,
        status=active.status,
        opened_at=as_utc(active.opened_at).isoformat(),
        present_count=present,
        late_count=late,
        waiting_count=max(total - present - late, 0),
        total_roster=total,
        spotlight=spotlight,
        server_time=datetime.now(UTC).isoformat(),
    )


async def _live_event_generator(
    kind: str, subject_id: UUID, laboratory_id: UUID
) -> AsyncGenerator[str, None]:
    """Stream SSE: kirim snapshot ringan hanya saat berubah (hash), tick 1 dtk."""
    last_digest = ""
    ticks = 0
    while True:
        try:
            with get_session_factory()() as db:
                lab = db.get(Laboratory, laboratory_id)
                if lab is None or not lab.is_active:
                    yield 'event: error\ndata: {"code":"laboratory_not_found"}\n\n'
                    return
                if kind == "kiosk":
                    device = db.get(Device, subject_id)
                    if device is None or not device.is_active:
                        yield 'event: error\ndata: {"code":"device_not_found"}\n\n'
                        return
                    kiosk = db.scalar(
                        select(KioskScreen).where(
                            KioskScreen.device_id == device.id,
                            KioskScreen.laboratory_id == device.laboratory_id,
                            KioskScreen.is_active.is_(True),
                        )
                    )
                    if kiosk is None or laboratory_id != lab.id:
                        yield 'event: error\ndata: {"code":"kiosk_not_found"}\n\n'
                        return
                update = _build_live_update(lab, db)
            payload = update.model_dump(mode="json")
            digest = _snapshot_digest(payload)
            if digest != last_digest:
                last_digest = digest
                yield f"event: snapshot\ndata: {json.dumps(payload)}\n\n"
            ticks += 1
            if ticks % 15 == 0:
                yield ": ping\n\n"
            await asyncio.sleep(1)
        except (asyncio.CancelledError, GeneratorExit):
            break
        except Exception:
            yield 'event: error\ndata: {"code":"stream_unavailable"}\n\n'
            return


def _snapshot_digest(payload: dict[str, object]) -> str:
    """Hash perubahan data; server_time dikecualikan agar idle tidak berisik."""
    stable = {k: v for k, v in payload.items() if k != "server_time"}
    return hashlib.sha256(
        json.dumps(stable, sort_keys=True, default=str).encode()
    ).hexdigest()


SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _build_snapshot(
    lab: Laboratory, session: Session, *, light: bool = False
) -> PublicDisplayResponse:
    active = _find_active_session(lab, session)
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
        students=[] if light else students,
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
        snapshot=_build_snapshot(lab, session, light=request.light),
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
    light: Annotated[bool, Query()] = False,
) -> PublicDisplayResponse:
    claims = decode_display_token(token, settings)
    if claims is None or claims.kind != "lab":
        raise ApiProblem(401, "display_token_invalid", "Sesi layar tidak valid.")
    lab = session.get(Laboratory, claims.laboratory_id)
    if lab is None or not lab.is_active:
        raise ApiProblem(404, "laboratory_not_found", "Laboratorium tidak ditemukan.")
    return _build_snapshot(lab, session, light=light)


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
        snapshot=_build_snapshot(lab, session, light=request.light),
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
    light: Annotated[bool, Query()] = False,
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
    return _build_snapshot(lab, session, light=light)


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


def _require_lab_stream_target(
    kind: str, claims_subject: UUID, claims_lab: UUID, session: Session
) -> Laboratory:
    lab = session.get(Laboratory, claims_lab)
    if lab is None or not lab.is_active:
        raise ApiProblem(404, "laboratory_not_found", "Laboratorium tidak ditemukan.")
    if kind == "kiosk":
        device = session.get(Device, claims_subject)
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
        if claims_lab != lab.id:
            raise ApiProblem(401, "display_token_invalid", "Sesi layar tidak valid.")
    return lab


@router.get(
    "/display/stream",
    responses={
        **OPENAPI_ERROR_RESPONSES,
        200: {
            "description": "Aliran SSE; setiap event snapshot memakai KioskLiveUpdate.",
            "content": {
                "text/event-stream": {
                    "schema": {"$ref": "#/components/schemas/KioskLiveUpdate"}
                }
            },
        },
    },
    summary="SSE live kiosk updates (lab token, no login)",
)
def stream_lab_display(
    session: DbSession,
    settings: AuthDep,
    token: Annotated[str, Query(min_length=16, max_length=1024)],
) -> StreamingResponse:
    claims = decode_display_token(token, settings)
    if claims is None or claims.kind != "lab":
        raise ApiProblem(401, "display_token_invalid", "Sesi layar tidak valid.")
    _require_lab_stream_target("lab", claims.subject_id, claims.laboratory_id, session)
    # Stream tak berujung: kembalikan koneksi pool segera, generator buka sesi
    # singkat per tick agar kiosk tidak menahan koneksi selama berjam-jam.
    session.close()
    return StreamingResponse(
        _live_event_generator("lab", claims.subject_id, claims.laboratory_id),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get(
    "/kiosk-display/stream",
    responses={
        **OPENAPI_ERROR_RESPONSES,
        200: {
            "description": "Aliran SSE; setiap event snapshot memakai KioskLiveUpdate.",
            "content": {
                "text/event-stream": {
                    "schema": {"$ref": "#/components/schemas/KioskLiveUpdate"}
                }
            },
        },
    },
    summary="SSE live kiosk updates (kiosk token, no login)",
)
def stream_kiosk_display(
    session: DbSession,
    settings: AuthDep,
    token: Annotated[str, Query(min_length=16, max_length=1024)],
) -> StreamingResponse:
    claims = decode_display_token(token, settings)
    if claims is None or claims.kind != "kiosk":
        raise ApiProblem(401, "display_token_invalid", "Sesi layar tidak valid.")
    _require_lab_stream_target(
        "kiosk", claims.subject_id, claims.laboratory_id, session
    )
    # Lihat catatan penutupan sesi pada stream lab di atas.
    session.close()
    return StreamingResponse(
        _live_event_generator("kiosk", claims.subject_id, claims.laboratory_id),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


def _rotate_display_token(
    kind: str,
    request: DisplayRotateRequest,
    session: Session,
    settings: AuthSettings,
) -> DisplaySessionResponse:
    """Terbitkan token pengganti; token lama tetap hidup sampai kedaluwarsa.

    Kiosk memakai ini untuk rotasi proaktif sebelum token habis (lihat
    DisplayView). PIN tidak diminta ulang; cakupan lab/perangkat dicek ulang.
    """
    claims = decode_display_token(request.display_token, settings)
    if claims is None or claims.kind != kind:
        raise ApiProblem(401, "display_token_invalid", "Sesi layar tidak valid.")
    _require_lab_stream_target(kind, claims.subject_id, claims.laboratory_id, session)
    lab = session.get(Laboratory, claims.laboratory_id)
    if lab is None or not lab.is_active:
        raise ApiProblem(404, "laboratory_not_found", "Laboratorium tidak ditemukan.")
    token, ttl = issue_display_token(
        kind, claims.subject_id, claims.laboratory_id, settings
    )
    return DisplaySessionResponse(
        display_token=token,
        expires_in_seconds=ttl,
        snapshot=_build_snapshot(lab, session, light=True),
    )


@router.post(
    "/display/rotate",
    response_model=DisplaySessionResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Rotate a lab display token (no login)",
)
def rotate_lab_display(
    request: DisplayRotateRequest,
    session: DbSession,
    settings: AuthDep,
) -> DisplaySessionResponse:
    return _rotate_display_token("lab", request, session, settings)


@router.post(
    "/kiosk-display/rotate",
    response_model=DisplaySessionResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Rotate a kiosk display token (no login)",
)
def rotate_kiosk_display(
    request: DisplayRotateRequest,
    session: DbSession,
    settings: AuthDep,
) -> DisplaySessionResponse:
    return _rotate_display_token("kiosk", request, session, settings)
