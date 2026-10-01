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

    def __init__(self) -> None:
        self._requests: dict[str, deque[float]] = {}
        self._lock = Lock()

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
            for old_key, timestamps in tuple(self._requests.items()):
                while timestamps and timestamps[0] <= cutoff:
                    timestamps.popleft()
                if not timestamps:
                    self._requests.pop(old_key, None)
            timestamps = self._requests.setdefault(key, deque())
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
