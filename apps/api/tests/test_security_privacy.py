from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from presensi_api.http_security import (
    RequestBodySizeLimitMiddleware,
    SecurityConfigurationError,
    add_restrictive_cors,
    configure_multipart_memory_only,
    parse_cors_allowed_origins,
)
from presensi_api.retention import recognition_event_retention_days


def test_cors_accepts_explicit_https_origins_and_local_development_origins() -> None:
    assert parse_cors_allowed_origins(
        "https://school.example.edu, http://localhost:5173,https://school.example.edu/"
    ) == ("https://school.example.edu", "http://localhost:5173")


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "https://*.example.edu",
        "http://school.example.edu",
        "https://school.example.edu/admin",
        "https://school.example.edu:invalid",
        "https://user:password@school.example.edu",
    ],
)
def test_cors_rejects_wildcards_insecure_remote_http_and_non_origins(
    value: str,
) -> None:
    with pytest.raises(SecurityConfigurationError):
        parse_cors_allowed_origins(value)


def test_cors_middleware_allows_only_the_configured_origin() -> None:
    app = FastAPI()
    add_restrictive_cors(app, ("https://school.example.edu",))

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(app)
    allowed = client.options(
        "/health",
        headers={
            "Origin": "https://school.example.edu",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    denied = client.get("/health", headers={"Origin": "https://untrusted.example"})

    assert allowed.status_code == 200
    assert (
        allowed.headers["access-control-allow-origin"] == "https://school.example.edu"
    )
    assert allowed.headers.get("access-control-allow-credentials") == "true"
    assert (
        "x-presensi-session"
        in allowed.headers["access-control-allow-headers"].casefold()
    )
    assert "access-control-allow-origin" not in denied.headers


def test_multipart_upload_spooling_is_kept_above_the_request_limit() -> None:
    from starlette.formparsers import MultiPartParser

    configure_multipart_memory_only(16 * 1024 * 1024)
    assert MultiPartParser.spool_max_size >= 16 * 1024 * 1024


def test_recognition_event_retention_setting_is_bounded_and_configurable() -> None:
    assert (
        recognition_event_retention_days(
            {"PRESENSI_RECOGNITION_EVENT_RETENTION_DAYS": "45"}
        )
        == 45
    )
    with pytest.raises(ValueError):
        recognition_event_retention_days(
            {"PRESENSI_RECOGNITION_EVENT_RETENTION_DAYS": "0"}
        )


def test_oversized_request_body_is_rejected_without_echoing_body() -> None:
    app = FastAPI()
    app.add_middleware(RequestBodySizeLimitMiddleware, max_bytes=16)

    @app.post("/upload")
    async def upload(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    secret_frame_marker = b"synthetic-private-frame-payload"
    response = TestClient(app).post("/upload", content=secret_frame_marker)

    assert response.status_code == 413
    assert secret_frame_marker.decode() not in response.text
    assert response.json()["error"]["code"] == "file_too_large"
