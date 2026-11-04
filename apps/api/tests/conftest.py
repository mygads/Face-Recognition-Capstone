"""Shared fixtures for the Core API test-suite."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from presensi_api.main import app


@pytest.fixture(autouse=True)
def _reset_request_rate_limiter() -> Generator[None, None, None]:
    """Isolate rate-limit buckets between tests (process-local limiter)."""
    app.state.request_rate_limiter.reset()
    yield
    app.state.request_rate_limiter.reset()
