"""AI readiness must surface the central apply error, not just revisions.

An admin can publish a combination the Core API schema accepts but the
central worker rejects at apply time (e.g. an unreachable consensus
minimum). The AI /health already reports ``configuration_sync_error_code``;
readiness must forward it (sanitized) so AiSetupView can tell a rejection
apart from a network outage.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from presensi_api.api.security.dependencies import get_current_user
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
from presensi_api.api.v1.routers import system_status
from presensi_api.api.v1.routers.system_status import get_ai_readiness
from presensi_api.db.base import Base
from presensi_api.db.session import get_db_session
from presensi_api.main import app


class _FakeHealthResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self, _limit: int = -1) -> bytes:
        return self._body

    def __enter__(self) -> _FakeHealthResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _central_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRESENSI_LOCAL_AI_PROFILE", "central")
    monkeypatch.setenv("PRESENSI_AI_SERVICE_BASE_URL", "http://ai-service.test:8001")
    monkeypatch.setenv("PRESENSI_ENROLLMENT_YUNET_MODEL_PATH", "")
    monkeypatch.setenv("PRESENSI_ENROLLMENT_SFACE_MODEL_PATH", "")


def _serve_ai_health(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    def fake_urlopen(_url: str, timeout: float = 0) -> _FakeHealthResponse:
        assert timeout > 0
        return _FakeHealthResponse(payload)

    monkeypatch.setattr(system_status, "urlopen", fake_urlopen)


def _healthy_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "ok",
        "models_ready": True,
        "model_version": "central-v3",
        "thresholds_configured": True,
        "recognition_ready": True,
        "configuration_revision": 3,
        "configuration_sync_status": "applied",
    }
    payload.update(overrides)
    return payload


def test_central_sync_rejection_error_code_is_forwarded(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    """A central apply rejection must reach the admin with its reason."""
    _central_env(monkeypatch)
    _serve_ai_health(
        monkeypatch,
        _healthy_payload(
            configuration_sync_status="error",
            configuration_sync_error_code="configuration_rejected",
        ),
    )
    readiness = get_ai_readiness(db_session)
    assert readiness.central_ai_config_sync_status == "error"
    assert readiness.central_ai_config_sync_error_code == "configuration_rejected"


def test_central_sync_error_code_is_sanitized(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    """Non-code payloads (or missing codes) must not leak into the UI."""
    _central_env(monkeypatch)
    for bad_code in (None, "", "   ", "not a code!!", 42):
        _serve_ai_health(
            monkeypatch,
            _healthy_payload(
                configuration_sync_status="error",
                configuration_sync_error_code=bad_code,
            ),
        )
        readiness = get_ai_readiness(db_session)
        assert readiness.central_ai_config_sync_error_code is None

    # Overlong codes are truncated like the edge error_code convention.
    _serve_ai_health(
        monkeypatch,
        _healthy_payload(
            configuration_sync_status="error",
            configuration_sync_error_code="x" * 200,
        ),
    )
    readiness = get_ai_readiness(db_session)
    assert readiness.central_ai_config_sync_error_code == "x" * 64


def test_edge_profile_reports_no_central_sync_error(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    """AI_EDGE responses must leave the central error code empty."""
    monkeypatch.setenv("PRESENSI_LOCAL_AI_PROFILE", "edge")

    def exploding_urlopen(*args: object, **kwargs: object) -> object:
        raise AssertionError("AI_EDGE must not query the central health endpoint")

    monkeypatch.setattr(system_status, "urlopen", exploding_urlopen)
    readiness = get_ai_readiness(db_session)
    assert readiness.deployment_profile == "AI_EDGE"
    assert readiness.central_ai_config_sync_status is None
    assert readiness.central_ai_config_sync_error_code is None


def test_ai_readiness_route_serves_readiness_over_http(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    """Regression: the route must serve get_ai_readiness, not the helper.

    The readiness decorator once sat on ``_central_sync_error_code`` (a
    body-taking helper), so a plain GET answered 422 instead of readiness
    and AiSetupView never saw sync status or the apply error code.
    """
    _central_env(monkeypatch)
    _serve_ai_health(
        monkeypatch,
        _healthy_payload(
            configuration_sync_status="error",
            configuration_sync_error_code="configuration_rejected",
        ),
    )
    factory = sessionmaker(bind=db_session.bind, expire_on_commit=False)

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=UUID("00000000-0000-4000-8000-000000000099"),
        email="admin@example.test",
        full_name="Synthetic Admin",
        roles=frozenset({RoleCode.ADMIN}),
    )
    try:
        response = TestClient(app).get("/api/v1/admin/system/ai-readiness")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["central_ai_config_sync_status"] == "error"
    assert body["central_ai_config_sync_error_code"] == "configuration_rejected"
