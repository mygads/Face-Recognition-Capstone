from __future__ import annotations

from collections import deque
from threading import Lock
from time import monotonic
from typing import Annotated

from fastapi import Depends, Request

from presensi_api.api.errors import ApiProblem
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.device_credentials import (
    AuthenticatedDevice,
    authenticate_device,
)
from presensi_api.api.security.roles import AuthenticatedUser, Permission


class SlidingWindowRateLimiter:
    """Small process-local limiter for already-authenticated principals."""

    #: Full-table sweeps are amortized: every request prunes only its own key,
    #: while the O(N) expired-key sweep runs once per this many calls so steady
    #: heartbeat/device traffic stays O(1) per request.
    _FULL_SWEEP_EVERY = 128

    def __init__(self) -> None:
        self._requests: dict[str, deque[float]] = {}
        self._lock = Lock()
        self._calls_since_sweep = 0

    def reset(self) -> None:
        """Drop all buckets; used by the test-suite to isolate rate-limit tests."""
        with self._lock:
            self._requests.clear()
            self._calls_since_sweep = 0

    def allow(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float = 60.0,
        now: float | None = None,
    ) -> bool:
        if limit < 1 or window_seconds <= 0:
            raise ValueError("Rate limit and window must be positive.")
        current = monotonic() if now is None else now
        cutoff = current - window_seconds
        with self._lock:
            # Amortized sweep runs before the per-key update so it can never
            # evict the bucket this request is about to append to.
            self._calls_since_sweep += 1
            if self._calls_since_sweep >= self._FULL_SWEEP_EVERY:
                self._calls_since_sweep = 0
                for old_key, other in tuple(self._requests.items()):
                    while other and other[0] <= cutoff:
                        other.popleft()
                    if not other:
                        self._requests.pop(old_key, None)
            timestamps = self._requests.get(key)
            if timestamps is None:
                timestamps = self._requests[key] = deque()
            else:
                while timestamps and timestamps[0] <= cutoff:
                    timestamps.popleft()
            if len(timestamps) >= limit:
                return False
            timestamps.append(current)
            return True


def rate_limited_device(
    principal: Annotated[AuthenticatedDevice, Depends(authenticate_device)],
    request: Request,
) -> AuthenticatedDevice:
    limiter: SlidingWindowRateLimiter = request.app.state.request_rate_limiter
    limit: int = request.app.state.device_requests_per_minute
    if not limiter.allow(f"device:{principal.device.id}", limit=limit):
        raise ApiProblem(
            429,
            "device_rate_limit_exceeded",
            "Perangkat mengirim permintaan terlalu cepat. Coba lagi sebentar.",
        )
    return principal


def rate_limited_enrollment_operator(
    principal: Annotated[
        AuthenticatedUser, Depends(require_permissions(Permission.ENROLLMENT_MANAGE))
    ],
    request: Request,
) -> AuthenticatedUser:
    limiter: SlidingWindowRateLimiter = request.app.state.request_rate_limiter
    limit: int = request.app.state.enrollment_requests_per_minute
    if not limiter.allow(f"enrollment-user:{principal.id}", limit=limit):
        raise ApiProblem(
            429,
            "enrollment_rate_limit_exceeded",
            "Enrollment terlalu sering dikirim. Coba lagi sebentar.",
        )
    return principal


DeviceActor = Annotated[AuthenticatedDevice, Depends(rate_limited_device)]
EnrollmentOperator = Annotated[
    AuthenticatedUser, Depends(rate_limited_enrollment_operator)
]


def enforce_login_rate_limit(request: Request, email: str) -> None:
    """Bound password-guessing and argon2 CPU burn before any DB work.

    Two buckets: per-email (a targeted account cannot be hammered even from
    a botnet) and per-IP (one client cannot spray many accounts or flood
    argon2 verifies). Rejected attempts return 429 without an audit row so
    a flood cannot bloat `audit_logs` either. Limits come from app.state so
    tests can tighten them without touching production defaults.
    """
    limiter: SlidingWindowRateLimiter = request.app.state.request_rate_limiter
    # Form usernames are unbounded; cap the key so a giant payload cannot
    # bloat limiter memory (real emails fit in 254 chars).
    normalized = email.strip().casefold()[:256]
    email_limit: int = request.app.state.login_email_attempts_per_minute
    if not limiter.allow(f"login:email:{normalized}", limit=email_limit):
        raise ApiProblem(
            429,
            "auth_login_rate_limit_exceeded",
            "Terlalu banyak percobaan masuk untuk akun ini. Coba lagi sebentar.",
            headers={"Retry-After": "60"},
        )
    client_ip = request.client.host if request.client is not None else "unknown"
    ip_limit: int = request.app.state.login_ip_attempts_per_minute
    if not limiter.allow(f"login:ip:{client_ip}", limit=ip_limit):
        raise ApiProblem(
            429,
            "auth_login_rate_limit_exceeded",
            "Terlalu banyak percobaan masuk dari jaringan ini. Coba lagi sebentar.",
            headers={"Retry-After": "60"},
        )
