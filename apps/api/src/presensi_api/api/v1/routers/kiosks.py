"""Kelola layar presensi (kiosk) per perangkat+lab. Admin penuh, laboran baca."""

from __future__ import annotations

import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.passwords import hash_password
from presensi_api.api.security.roles import AuthenticatedUser, Permission, RoleCode
from presensi_api.api.v1.schemas.common import PageResponse, Pagination
from presensi_api.api.v1.schemas.kiosks import (
    KioskCreateRequest,
    KioskPinResponse,
    KioskResponse,
    KioskUpdateRequest,
)
from presensi_api.db.models import AuditLog, Device, KioskScreen, Laboratory
from presensi_api.db.session import get_db_session
from presensi_api.session_lifecycle import as_utc

router = APIRouter(prefix="/kiosks", tags=["kiosks"])
DbSession = Annotated[Session, Depends(get_db_session)]
KioskManager = Annotated[
    AuthenticatedUser, Depends(require_permissions(Permission.MANAGE_SETTINGS))
]
KioskViewer = Annotated[
    AuthenticatedUser, Depends(require_permissions(Permission.DEVICE_OPERATE))
]


def _to_response(row: KioskScreen) -> KioskResponse:
    return KioskResponse(
        id=row.id,
        device_id=row.device_id,
        laboratory_id=row.laboratory_id,
        display_name=row.display_name,
        camera_label=row.camera_label,
        has_pin=bool(row.pin_hash),
        is_active=row.is_active,
        last_seen_at=as_utc(row.last_seen_at) if row.last_seen_at is not None else None,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
    )


def _scope_filter(principal: AuthenticatedUser, query: object) -> object:
    if RoleCode.ADMIN in principal.roles:
        return query

    # Laboran hanya melihat lab penugasannya; tanpa lab -> kosong.
    return query  # filter diterapkan di endpoint via session (lihat bawah)


@router.get(
    "",
    response_model=PageResponse[KioskResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List kiosk screens",
)
def list_kiosks(
    principal: KioskViewer,
    session: DbSession,
    laboratory_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[KioskResponse]:
    query = select(KioskScreen)
    if laboratory_id is not None:
        query = query.where(KioskScreen.laboratory_id == laboratory_id)
    if RoleCode.ADMIN not in principal.roles:
        from presensi_api.api.security.scope import laborant_lab_ids

        labs = laborant_lab_ids(session, principal.id)
        if labs:
            query = query.where(KioskScreen.laboratory_id.in_(labs))
        else:
            query = query.where(KioskScreen.id.is_(None))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(
        query.order_by(KioskScreen.display_name).limit(limit).offset(offset)
    ).all()
    return PageResponse(
        items=[_to_response(r) for r in rows],
        pagination=Pagination(total=total, limit=limit, offset=offset),
    )


@router.post(
    "",
    response_model=KioskResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Register a kiosk screen (ADMIN)",
)
def create_kiosk(
    request: KioskCreateRequest,
    principal: KioskManager,
    session: DbSession,
) -> KioskResponse:
    device = session.get(Device, request.device_id)
    lab = session.get(Laboratory, request.laboratory_id)
    if device is None:
        raise ApiProblem(404, "device_not_found", "Perangkat tidak ditemukan.")
    if lab is None:
        raise ApiProblem(404, "laboratory_not_found", "Laboratorium tidak ditemukan.")
    existing = session.scalar(
        select(KioskScreen).where(
            KioskScreen.device_id == request.device_id,
            KioskScreen.laboratory_id == request.laboratory_id,
        )
    )
    if existing is not None:
        raise ApiProblem(
            409, "kiosk_exists", "Layar untuk perangkat+lab ini sudah terdaftar."
        )
    row = KioskScreen(
        device_id=request.device_id,
        laboratory_id=request.laboratory_id,
        display_name=request.display_name.strip(),
        camera_label=request.camera_label.strip() if request.camera_label else None,
    )
    session.add(row)
    session.flush()
    session.add(
        AuditLog(
            action="kiosk.registered",
            actor_user_id=principal.id,
            entity_type="kiosk_screen",
            entity_id=row.id,
            after_state={
                "device_id": str(request.device_id),
                "laboratory_id": str(request.laboratory_id),
            },
        )
    )
    session.commit()
    session.refresh(row)
    return _to_response(row)


@router.patch(
    "/{kiosk_id}",
    response_model=KioskResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Update a kiosk screen (ADMIN)",
)
def update_kiosk(
    kiosk_id: UUID,
    request: KioskUpdateRequest,
    principal: KioskManager,
    session: DbSession,
) -> KioskResponse:
    row = session.get(KioskScreen, kiosk_id)
    if row is None:
        raise ApiProblem(404, "kiosk_not_found", "Layar tidak ditemukan.")
    before = {"display_name": row.display_name, "is_active": row.is_active}
    if request.display_name is not None:
        row.display_name = request.display_name.strip()
    if request.camera_label is not None:
        row.camera_label = request.camera_label.strip() or None
    if request.is_active is not None:
        row.is_active = request.is_active
    session.add(
        AuditLog(
            action="kiosk.updated",
            actor_user_id=principal.id,
            entity_type="kiosk_screen",
            entity_id=row.id,
            before_state=before,
            after_state={
                "display_name": row.display_name,
                "is_active": row.is_active,
            },
        )
    )
    session.commit()
    session.refresh(row)
    return _to_response(row)


@router.post(
    "/{kiosk_id}/pin",
    response_model=KioskPinResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Create/reset a kiosk PIN (ADMIN, shown once)",
)
def reset_kiosk_pin(
    kiosk_id: UUID,
    principal: KioskManager,
    session: DbSession,
) -> KioskPinResponse:
    row = session.get(KioskScreen, kiosk_id)
    if row is None:
        raise ApiProblem(404, "kiosk_not_found", "Layar tidak ditemukan.")
    pin = f"{secrets.randbelow(900000) + 100000:06d}"
    row.pin_hash = hash_password(pin)
    session.add(
        AuditLog(
            action="kiosk.pin_reset",
            actor_user_id=principal.id,
            entity_type="kiosk_screen",
            entity_id=row.id,
            after_state={"has_pin": True},
        )
    )
    session.commit()
    return KioskPinResponse(id=row.id, temporary_pin=pin)


@router.delete(
    "/{kiosk_id}",
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Revoke a kiosk screen (ADMIN)",
)
def revoke_kiosk(
    kiosk_id: UUID,
    principal: KioskManager,
    session: DbSession,
) -> dict[str, object]:
    row = session.get(KioskScreen, kiosk_id)
    if row is None:
        raise ApiProblem(404, "kiosk_not_found", "Layar tidak ditemukan.")
    row.is_active = False
    row.pin_hash = None
    session.add(
        AuditLog(
            action="kiosk.revoked",
            actor_user_id=principal.id,
            entity_type="kiosk_screen",
            entity_id=row.id,
            after_state={"is_active": False},
        )
    )
    session.commit()
    return {"revoked": True}
