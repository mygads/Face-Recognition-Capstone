"""Regresi: sesi layar publik via POST PIN ke token (tanpa PIN di URL)."""

from __future__ import annotations

import asyncio
from collections.abc import Generator

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from presensi_api.api.security.config import AuthSettings
from presensi_api.api.security.dependencies import get_auth_settings
from presensi_api.api.security.passwords import hash_password
from presensi_api.db.base import Base
from presensi_api.db.models import Device, KioskScreen, Laboratory
from presensi_api.db.session import get_db_session
from presensi_api.main import app

TEST_SETTINGS = AuthSettings(signing_secret="x" * 40)


@pytest.fixture
def display_database() -> Generator[sessionmaker[Session], None, None]:
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
    with factory.begin() as session:
        lab = Laboratory(
            code="LAB-DISP", name="Lab Display", display_pin_hash=hash_password("1234")
        )
        session.add(lab)
        session.flush()
        device = Device(
            laboratory_id=lab.id,
            name="edge-pc-disp-01",
            device_type="edge_pc",
            deployment_profile="AI_EDGE",
        )
        session.add(device)
        session.flush()
        session.add(
            KioskScreen(
                device_id=device.id,
                laboratory_id=lab.id,
                display_name="Kiosk Uji",
                pin_hash=hash_password("9999"),
            )
        )
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


def post_json(path: str, payload: dict[str, object]) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.post(path, json=payload)

    return asyncio.run(send())


def get(path: str) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get(path)

    return asyncio.run(send())


def _ids(factory: sessionmaker[Session]) -> tuple[str, str]:
    with factory() as session:
        lab = session.query(Laboratory).one()
        dev = session.query(Device).one()
        return str(lab.id), str(dev.id)


def test_lab_session_then_token_polling(
    display_database: sessionmaker[Session],
) -> None:
    lab_id, _ = _ids(display_database)
    opened = post_json(
        "/api/v1/public/display/session", {"laboratory_id": lab_id, "pin": "1234"}
    )
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert body["display_token"]
    assert body["snapshot"]["laboratory_id"] == lab_id
    assert "pin" not in body["display_token"]

    snap = get(f"/api/v1/public/display?token={body['display_token']}")
    assert snap.status_code == 200, snap.text
    assert snap.json()["laboratory_id"] == lab_id

    bad = get("/api/v1/public/display?token=" + "salah-token-salah-token")
    assert bad.status_code == 401, bad.text
    # PIN tidak lagi diterima sebagai query URL.
    legacy = get(f"/api/v1/public/display?laboratory_id={lab_id}&pin=1234")
    assert legacy.status_code == 422, legacy.text


def test_lab_pin_lockout_after_repeated_failures(
    display_database: sessionmaker[Session],
) -> None:
    lab_id, _ = _ids(display_database)
    for _ in range(5):
        bad = post_json(
            "/api/v1/public/display/session", {"laboratory_id": lab_id, "pin": "0000"}
        )
        assert bad.status_code == 403, bad.text
    locked = post_json(
        "/api/v1/public/display/session", {"laboratory_id": lab_id, "pin": "0000"}
    )
    assert locked.status_code == 429, locked.text
    even_correct = post_json(
        "/api/v1/public/display/session", {"laboratory_id": lab_id, "pin": "1234"}
    )
    assert even_correct.status_code == 429, even_correct.text


def test_kiosk_session_then_token_polling(
    display_database: sessionmaker[Session],
) -> None:
    _, dev_id = _ids(display_database)
    opened = post_json(
        "/api/v1/public/kiosk-display/session", {"device_id": dev_id, "pin": "9999"}
    )
    assert opened.status_code == 200, opened.text
    token = opened.json()["display_token"]
    snap = get(f"/api/v1/public/kiosk-display?token={token}")
    assert snap.status_code == 200, snap.text
