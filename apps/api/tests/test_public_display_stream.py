"""Regresi: stream SSE kiosk ringan (agregat + sorotan, tanpa roster).

Catatan: httpx ASGITransport mem-buffer seluruh body sehingga tidak dapat
dipakai untuk membaca stream tak berujung. Test memakai endpoint langsung
(validasi + StreamingResponse) dan generator event secara langsung.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Generator
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi.responses import StreamingResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import presensi_api.api.v1.routers.public_display as display_module
from presensi_api.api.errors import ApiProblem
from presensi_api.api.security.config import AuthSettings
from presensi_api.api.security.dependencies import (
    decode_display_token,
    get_auth_settings,
    issue_display_token,
)
from presensi_api.api.security.passwords import hash_password
from presensi_api.db.base import Base
from presensi_api.db.models import Device, KioskScreen, Laboratory
from presensi_api.db.session import get_db_session
from presensi_api.main import app

TEST_SETTINGS = AuthSettings(signing_secret="y" * 40)


@pytest.fixture
def stream_database(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_auth_settings] = lambda: TEST_SETTINGS
    # Generator SSE memakai factory proses; arahkan ke sqlite uji.
    monkeypatch.setattr(display_module, "get_session_factory", lambda: factory)
    with factory.begin() as session:
        lab = Laboratory(
            code="LAB-SSE", name="Lab SSE", display_pin_hash=hash_password("1234")
        )
        session.add(lab)
        session.flush()
        device = Device(
            laboratory_id=lab.id,
            name="edge-pc-sse-01",
            device_type="edge_pc",
            deployment_profile="AI_EDGE",
        )
        session.add(device)
        session.flush()
        session.add(
            KioskScreen(
                device_id=device.id,
                laboratory_id=lab.id,
                display_name="Kiosk SSE",
                pin_hash=hash_password("9999"),
            )
        )
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


def _ids(factory: sessionmaker[Session]) -> tuple[str, str]:
    with factory() as session:
        lab = session.query(Laboratory).one()
        dev = session.query(Device).one()
        return str(lab.id), str(dev.id)


def _collect_first_event(
    gen: AsyncGenerator[str, None],
) -> tuple[str, dict[str, Any] | None]:
    async def run() -> tuple[str, dict[str, Any] | None]:
        async for raw in gen:
            for block in raw.split("\n\n"):
                if block.startswith("event: snapshot"):
                    for line in block.splitlines():
                        if line.startswith("data: "):
                            return "snapshot", json.loads(line[6:])
                if block.startswith("event: error"):
                    for line in block.splitlines():
                        if line.startswith("data: "):
                            return "error", json.loads(line[6:])
                    return "error", None
        raise AssertionError("stream berakhir tanpa event")

    return asyncio.run(run())


def test_lab_stream_rejects_bad_token_over_http(
    stream_database: sessionmaker[Session],
) -> None:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get(
                "/api/v1/public/display/stream?token=salah-token-salah-token"
            )

    resp = asyncio.run(send())
    assert resp.status_code == 401, resp.text


def test_kiosk_stream_rejects_bad_token_over_http(
    stream_database: sessionmaker[Session],
) -> None:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get(
                "/api/v1/public/kiosk-display/stream?token=salah-token-salah-token"
            )

    resp = asyncio.run(send())
    assert resp.status_code == 401, resp.text


def test_lab_endpoint_returns_event_stream(
    stream_database: sessionmaker[Session],
) -> None:
    lab_id, _ = _ids(stream_database)
    with stream_database() as session:
        lab = session.query(Laboratory).one()
        real_token, _ = issue_display_token("lab", lab.id, lab.id, TEST_SETTINGS)
        assert decode_display_token(real_token, TEST_SETTINGS) is not None
        response = display_module.stream_lab_display(session, TEST_SETTINGS, real_token)
    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/event-stream"


def test_lab_stream_emits_lightweight_snapshot(
    stream_database: sessionmaker[Session],
) -> None:
    lab_id, _ = _ids(stream_database)
    with stream_database() as session:
        lab = session.query(Laboratory).one()
        token, _ = issue_display_token("lab", lab.id, lab.id, TEST_SETTINGS)
        claims = decode_display_token(token, TEST_SETTINGS)
        assert claims is not None
        gen = display_module._live_event_generator(
            "lab", claims.subject_id, claims.laboratory_id
        )
        kind, snap = _collect_first_event(gen)
        asyncio.run(gen.aclose())
    assert lab_id == str(lab.id)
    assert kind == "snapshot"
    assert snap is not None
    assert snap["laboratory_id"] == lab_id
    assert "students" not in snap
    assert snap["total_roster"] == 0
    assert snap["waiting_count"] == 0
    assert snap["spotlight"] is None
    assert snap["server_time"]


def test_stream_emits_error_for_unknown_lab(
    stream_database: sessionmaker[Session],
) -> None:
    gen = display_module._live_event_generator("lab", UUID(int=1), UUID(int=2))
    kind, payload = _collect_first_event(gen)
    asyncio.run(gen.aclose())
    assert kind == "error"
    assert payload is not None
    assert payload.get("code") == "laboratory_not_found"


def test_stream_endpoints_reject_mismatched_kind(
    stream_database: sessionmaker[Session],
) -> None:
    with stream_database() as session:
        lab = session.query(Laboratory).one()
        device = session.query(Device).one()
        lab_token, _ = issue_display_token("lab", lab.id, lab.id, TEST_SETTINGS)
        kiosk_token, _ = issue_display_token("kiosk", device.id, lab.id, TEST_SETTINGS)
        with pytest.raises(ApiProblem):
            display_module.stream_lab_display(session, TEST_SETTINGS, kiosk_token)
        with pytest.raises(ApiProblem):
            display_module.stream_kiosk_display(session, TEST_SETTINGS, lab_token)
        response = display_module.stream_kiosk_display(
            session, TEST_SETTINGS, kiosk_token
        )
        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"


def test_snapshot_digest_ignores_server_time() -> None:
    base = {
        "laboratory_id": "lab-1",
        "present_count": 1,
        "waiting_count": 2,
        "spotlight": None,
    }
    tick_a = {**base, "server_time": "2026-11-10T00:00:00+00:00"}
    tick_b = {**base, "server_time": "2026-11-10T00:00:01+00:00"}
    assert display_module._snapshot_digest(tick_a) == display_module._snapshot_digest(
        tick_b
    )
    changed = {**base, "present_count": 2, "server_time": tick_a["server_time"]}
    assert display_module._snapshot_digest(changed) != display_module._snapshot_digest(
        tick_a
    )
