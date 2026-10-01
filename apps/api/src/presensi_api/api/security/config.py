from __future__ import annotations

import os
from dataclasses import dataclass, field


class AuthConfigurationError(RuntimeError):
    """Raised when signing configuration is missing or invalid."""


@dataclass(frozen=True)
class AuthSettings:
    signing_secret: str = field(repr=False)
    access_token_ttl_minutes: int = 15
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

        return cls(
            signing_secret=signing_secret,
            access_token_ttl_minutes=access_token_ttl_minutes,
        )
