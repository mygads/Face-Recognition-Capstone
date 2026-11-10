"""Regresi: registrasi kiosk layar + reset PIN (audit memakai id baris)."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from uuid import UUID

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from presensi_api.api.security.dependencies import get_current_user
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
from presensi_api.db.base import Base
from presensi_api.db.models import Device, Laboratory, User
from presensi_api.db.session import get_db_session
from presensi_api.main import app


@pytest.fixture
def kiosk_database() -> Generator[sessionmaker[Session], None, None]:
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
    principal = AuthenticatedUser(
        id=UUID(int=43),
        email="admin@example.test",
        full_name="Test Admin",
        roles=frozenset({RoleCode.ADMIN}),
    )
    app.dependency_overrides[get_current_user] = lambda: principal
    with factory.begin() as session:
        session.add(
            User(
                id=principal.id,
                email=principal.email,
                full_name=principal.full_name,
                password_hash="unused-test-hash",
            )
        )
        lab = Laboratory(code="LAB-UJI", name="Lab Uji")
        session.add(lab)
        session.flush()
        session.add(
            Device(
                laboratory_id=lab.id,
                name="edge-pc-uji-01",
                device_type="edge_pc",
                deployment_profile="AI_EDGE",
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


def test_register_kiosk_writes_audit_with_row_id(
    kiosk_database: sessionmaker[Session],
) -> None:
    with kiosk_database() as session:
        lab = session.query(Laboratory).one()
        dev = session.query(Device).one()
        lab_id, dev_id = str(lab.id), str(dev.id)

    created = post_json(
        "/api/v1/kiosks",
        {
            "device_id": dev_id,
            "laboratory_id": lab_id,
            "display_name": "Kiosk Uji",
            "camera_label": "Pintu masuk",
        },
    )
    assert created.status_code == 201, created.text
    kiosk_id = created.json()["id"]
    assert created.json()["has_pin"] is False

    # Duplikat perangkat+lab ditolak, bukan 500.
    duplicate = post_json(
        "/api/v1/kiosks",
        {"device_id": dev_id, "laboratory_id": lab_id, "display_name": "Kiosk Uji 2"},
    )
    assert duplicate.status_code == 409

    # Reset PIN mengembalikan PIN sekali tampil dan menandai has_pin.
    async def reset() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.post(f"/api/v1/kiosks/{kiosk_id}/pin")

    pin = asyncio.run(reset())
    assert pin.status_code in (200, 201), pin.text
    assert len(pin.json()["temporary_pin"]) == 6

    from presensi_api.db.models import AuditLog, KioskScreen

    with kiosk_database() as session:
        row = session.get(KioskScreen, UUID(kiosk_id))
        assert row is not None and row.pin_hash
        audits = (
            session.query(AuditLog).filter(AuditLog.entity_type == "kiosk_screen").all()
        )
        assert audits, "registrasi kiosk harus tercatat di audit"
        assert {str(a.entity_id) for a in audits} == {kiosk_id}
