"""Shared fixtures for the Core API test-suite."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from presensi_api.main import app

_REQUEST_LIMIT_DEFAULTS = {
    name: getattr(app.state, name)
    for name in (
        "device_requests_per_minute",
        "enrollment_requests_per_minute",
        "login_email_attempts_per_minute",
        "login_ip_attempts_per_minute",
    )
}


@pytest.fixture(autouse=True)
def _reset_request_rate_limiter() -> Generator[None, None, None]:
    """Isolate rate-limit buckets between tests (process-local limiter)."""
    for name, value in _REQUEST_LIMIT_DEFAULTS.items():
        setattr(app.state, name, value)
    app.state.request_rate_limiter.reset()
    yield
    app.state.request_rate_limiter.reset()
