from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from presensi_api.db.models import Device
from presensi_api.db.session import get_db_session
from presensi_api.session_lifecycle import as_utc

DEVICE_CREDENTIAL_TTL_DAYS = 90
DEVICE_CREDENTIAL_OVERLAP_HOURS = 24
device_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class AuthenticatedDevice:
    device: Device
    used_current_credential: bool


def hash_device_credential(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def issue_device_credential() -> str:
    return secrets.token_urlsafe(48)


def rotate_device_credential(
    device: Device, *, now: datetime | None = None
) -> tuple[str, datetime, datetime | None]:
    current = now or datetime.now(UTC)
    token = issue_device_credential()
    previous_until = (
        current + timedelta(hours=DEVICE_CREDENTIAL_OVERLAP_HOURS)
        if device.credential_hash
        else None
    )
    device.previous_credential_hash = device.credential_hash
    device.previous_credential_expires_at = previous_until
    device.credential_hash = hash_device_credential(token)
    device.credential_expires_at = current + timedelta(days=DEVICE_CREDENTIAL_TTL_DAYS)
    return token, device.credential_expires_at, previous_until


def authenticate_device(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Security(device_bearer)
    ],
    x_device_id: Annotated[UUID | None, Header(alias="X-Device-ID")] = None,
    session: Session = Depends(get_db_session),
) -> AuthenticatedDevice:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid device credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or x_device_id is None:
        raise unauthorized
    device = session.get(Device, x_device_id)
    if device is None or not device.is_active:
        raise unauthorized
    current = datetime.now(UTC)
    token = credentials.credentials
    if not token.isascii():
        raise unauthorized
    provided_hash = hash_device_credential(token)
    matches_current = bool(
        device.credential_hash
        and device.credential_expires_at is not None
        and as_utc(device.credential_expires_at) > current
        and secrets.compare_digest(provided_hash, device.credential_hash)
    )
    if matches_current:
        return AuthenticatedDevice(device=device, used_current_credential=True)
    matches_previous = bool(
        device.previous_credential_hash
        and device.previous_credential_expires_at is not None
        and as_utc(device.previous_credential_expires_at) > current
        and secrets.compare_digest(provided_hash, device.previous_credential_hash)
    )
    if matches_previous:
        return AuthenticatedDevice(device=device, used_current_credential=False)
    raise unauthorized


def require_path_device(
    principal: AuthenticatedDevice, requested_device_id: UUID
) -> Device:
    if principal.device.id != requested_device_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device credential does not match the requested device.",
        )
    return principal.device
