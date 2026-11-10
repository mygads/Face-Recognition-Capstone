"""Jejak audit aktivitas (ADMIN). PIN/token/gambar/embedding tidak diekspos."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import AuthenticatedUser, Permission
from presensi_api.api.v1.schemas.common import ApiSchema, PageResponse, Pagination
from presensi_api.db.models import AuditLog
from presensi_api.db.session import get_db_session
from presensi_api.session_lifecycle import as_utc

router = APIRouter(prefix="/audit", tags=["audit"])
DbSession = Annotated[Session, Depends(get_db_session)]
AuditReader = Annotated[
    AuthenticatedUser, Depends(require_permissions(Permission.MANAGE_SETTINGS))
]

_SENSITIVE_KEYS = {"password", "pin", "token", "embedding", "image", "secret"}


def _redact(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(k): (
                "***"
                if any(s in str(k).lower() for s in _SENSITIVE_KEYS)
                else _redact(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


class AuditEntry(ApiSchema):
    id: UUID
    actor_user_id: UUID | None
    action: str
    entity_type: str
    entity_id: UUID
    before_state: dict[str, object] | None = None
    after_state: dict[str, object] | None = None
    created_at: object | None = None


@router.get(
    "/activity",
    response_model=PageResponse[AuditEntry],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List audit activity (ADMIN)",
)
def list_audit_activity(
    principal: AuditReader,
    session: DbSession,
    action: str | None = None,
    entity_type: str | None = None,
    actor_user_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[AuditEntry]:
    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action == action)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if actor_user_id is not None:
        query = query.where(AuditLog.actor_user_id == actor_user_id)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(
        query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return PageResponse(
        items=[
            AuditEntry(
                id=r.id,
                actor_user_id=r.actor_user_id,
                action=r.action,
                entity_type=r.entity_type,
                entity_id=r.entity_id,
                before_state=_redact(r.before_state),  # type: ignore[arg-type]
                after_state=_redact(r.after_state),  # type: ignore[arg-type]
                created_at=as_utc(r.created_at),
            )
            for r in rows
        ],
        pagination=Pagination(total=total, limit=limit, offset=offset),
    )
