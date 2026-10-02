from __future__ import annotations

import os
from dataclasses import dataclass, field


class AuthConfigurationError(RuntimeError):
    """Raised when signing configuration is missing or invalid."""


@dataclass(frozen=True)
class AuthSettings:
    signing_secret: str = field(repr=False)
    access_token_ttl_minutes: int = 15
    session_ttl_hours: int = 24
    session_cookie_secure: bool = True
    issuer: str = "presensi-core-api"

    @classmethod
    def from_environment(cls) -> AuthSettings:
        signing_secret = os.getenv("JWT_SECRET", "")
        if len(signing_secret.encode("utf-8")) < 32:
            raise AuthConfigurationError("JWT_SECRET must contain at least 32 bytes.")

        raw_ttl = os.getenv("JWT_ACCESS_TOKEN_TTL_MINUTES", "15")
        try:
            access_token_ttl_minutes = int(raw_ttl)
        except ValueError as exc:
            raise AuthConfigurationError(
                "JWT_ACCESS_TOKEN_TTL_MINUTES must be an integer."
            ) from exc
        if not 5 <= access_token_ttl_minutes <= 60:
            raise AuthConfigurationError(
                "JWT_ACCESS_TOKEN_TTL_MINUTES must be between 5 and 60."
            )

        raw_session_ttl = os.getenv("JWT_SESSION_TTL_HOURS", "24")
        try:
            session_ttl_hours = int(raw_session_ttl)
        except ValueError as exc:
            raise AuthConfigurationError(
                "JWT_SESSION_TTL_HOURS must be an integer."
            ) from exc
        if not 1 <= session_ttl_hours <= 168:
            raise AuthConfigurationError(
                "JWT_SESSION_TTL_HOURS must be between 1 and 168."
            )

        raw_cookie_secure = (
            os.getenv("JWT_SESSION_COOKIE_SECURE", "").strip().casefold()
        )
        if raw_cookie_secure:
            if raw_cookie_secure not in {"true", "false"}:
                raise AuthConfigurationError(
                    "JWT_SESSION_COOKIE_SECURE must be true or false."
                )
            session_cookie_secure = raw_cookie_secure == "true"
        else:
            session_cookie_secure = os.getenv(
                "APP_ENV", "production"
            ).casefold() not in {
                "development",
                "test",
            }

        return cls(
            signing_secret=signing_secret,
            access_token_ttl_minutes=access_token_ttl_minutes,
            session_ttl_hours=session_ttl_hours,
            session_cookie_secure=session_cookie_secure,
        )
