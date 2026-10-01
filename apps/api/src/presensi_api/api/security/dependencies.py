from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from presensi_api.api.security.config import AuthConfigurationError, AuthSettings
from presensi_api.api.security.roles import (
    AuthenticatedUser,
    Permission,
    principal_for_user,
)
from presensi_api.db.models import User
from presensi_api.db.session import get_db_session

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_auth_settings() -> AuthSettings:
    try:
        return AuthSettings.from_environment()
    except AuthConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        ) from exc


def issue_access_token(
    subject: UUID, settings: AuthSettings, *, now: datetime | None = None
) -> tuple[str, int]:
    issued_at = now or datetime.now(UTC)
    expires_in_seconds = settings.access_token_ttl_minutes * 60
    claims = {
        "sub": str(subject),
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=expires_in_seconds),
        "jti": str(uuid4()),
        "iss": settings.issuer,
        "token_use": "access",
    }
    token = jwt.encode(claims, settings.signing_secret, algorithm="HS256")
    return token, expires_in_seconds


def get_token_subject(
    token: Annotated[str, Depends(oauth2_scheme)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> UUID:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        claims = jwt.decode(
            token,
            settings.signing_secret,
            algorithms=["HS256"],
            issuer=settings.issuer,
            options={"require": ["sub", "iat", "exp", "jti", "iss", "token_use"]},
        )
        if claims.get("token_use") != "access":
            raise credentials_error
        user_id = UUID(claims["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise credentials_error from exc

    return user_id


def get_current_user(
    user_id: Annotated[UUID, Depends(get_token_subject)],
    session: Annotated[Session, Depends(get_db_session)],
) -> AuthenticatedUser:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_error
    principal = principal_for_user(session, user)
    if not principal.roles:
        raise credentials_error
    return principal


def require_permissions(*required: Permission) -> Callable[..., AuthenticatedUser]:
    def guard(
        principal: Annotated[AuthenticatedUser, Depends(get_current_user)],
    ) -> AuthenticatedUser:
        if not set(required).issubset(principal.permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            )
        return principal

    return guard
