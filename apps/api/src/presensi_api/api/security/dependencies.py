from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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
    subject: UUID,
    settings: AuthSettings,
    *,
    password_change_only: bool = False,
    token_version: int = 0,
    now: datetime | None = None,
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
        "password_change_only": password_change_only,
        "token_version": token_version,
    }
    token = jwt.encode(claims, settings.signing_secret, algorithm="HS256")
    return token, expires_in_seconds


@dataclass(frozen=True)
class BrowserSessionClaims:
    user_id: UUID
    session_id: UUID
    token_version: int


def issue_browser_session_token(
    subject: UUID,
    session_id: UUID,
    settings: AuthSettings,
    *,
    token_version: int = 0,
    now: datetime | None = None,
) -> str:
    issued_at = now or datetime.now(UTC)
    claims = {
        "sub": str(subject),
        "iat": issued_at,
        "exp": issued_at + timedelta(hours=settings.session_ttl_hours),
        "jti": str(session_id),
        "iss": settings.issuer,
        "token_use": "browser_session",
        "token_version": token_version,
    }
    return jwt.encode(claims, settings.signing_secret, algorithm="HS256")


def decode_browser_session_token(
    token: str, settings: AuthSettings
) -> BrowserSessionClaims | None:
    try:
        claims = jwt.decode(
            token,
            settings.signing_secret,
            algorithms=["HS256"],
            issuer=settings.issuer,
            options={"require": ["sub", "iat", "exp", "jti", "iss", "token_use"]},
        )
        if claims.get("token_use") != "browser_session":
            return None
        token_version = claims.get("token_version", 0)
        if type(token_version) is not int or token_version < 0:
            return None
        return BrowserSessionClaims(
            user_id=UUID(claims["sub"]),
            session_id=UUID(claims["jti"]),
            token_version=token_version,
        )
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return None


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: UUID
    password_change_only: bool
    token_version: int


def get_access_token_claims(
    token: Annotated[str, Depends(oauth2_scheme)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> AccessTokenClaims:
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
        password_change_only = claims.get("password_change_only", False)
        token_version = claims.get("token_version", 0)
        if not isinstance(password_change_only, bool):
            raise credentials_error
        if type(token_version) is not int or token_version < 0:
            raise credentials_error
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise credentials_error from exc

    return AccessTokenClaims(
        user_id=user_id,
        password_change_only=password_change_only,
        token_version=token_version,
    )


def get_current_user(
    claims: Annotated[AccessTokenClaims, Depends(get_access_token_claims)],
    session: Annotated[Session, Depends(get_db_session)],
) -> AuthenticatedUser:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user = session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise credentials_error
    if user.auth_token_version != claims.token_version:
        raise credentials_error
    if claims.password_change_only or user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Change the temporary password before using the application.",
        )
    principal = principal_for_user(session, user)
    if not principal.roles:
        raise credentials_error
    return principal


def get_password_change_user(
    claims: Annotated[AccessTokenClaims, Depends(get_access_token_claims)],
    session: Annotated[Session, Depends(get_db_session)],
) -> AuthenticatedUser:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user = session.get(User, claims.user_id)
    if (
        user is None
        or not user.is_active
        or user.auth_token_version != claims.token_version
    ):
        raise credentials_error
    return principal_for_user(session, user)


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
