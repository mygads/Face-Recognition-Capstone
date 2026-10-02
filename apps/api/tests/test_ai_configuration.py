from __future__ import annotations

from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from presensi_api.api.security.dependencies import get_current_user
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
from presensi_api.db.base import Base
from presensi_api.db.models import Device, Laboratory, User
from presensi_api.db.session import get_db_session
from presensi_api.main import app

DEVICE_ID = UUID("1ec0b107-6793-4a1a-b3ae-24273a334de5")
ADMIN_ID = UUID("20000000-0000-4000-8000-000000000001")
LAB_ID = UUID("30000000-0000-4000-8000-000000000001")


@pytest.fixture
def edge_settings_client() -> Generator[TestClient, None, None]:
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

    with factory.begin() as session:
        session.add_all(
            [
                User(
                    id=ADMIN_ID,
                    email="admin@example.test",
                    full_name="Synthetic Admin",
                    password_hash="test-hash",
                ),
                Laboratory(id=LAB_ID, code="LAB-AI", name="AI Test Lab"),
            ]
        )
        session.flush()
        session.add(
            Device(
                id=DEVICE_ID,
                laboratory_id=LAB_ID,
                name="Synthetic Edge Device",
                device_type="edge_pc",
                deployment_profile="AI_EDGE",
            )
        )
        session.flush()

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=ADMIN_ID,
        email="admin@example.test",
        full_name="Synthetic Admin",
        roles=frozenset({RoleCode.ADMIN}),
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_can_publish_edge_quality_defaults_without_thresholds(
    edge_settings_client: TestClient,
) -> None:
    response = edge_settings_client.put(
        f"/api/v1/admin/settings/devices/{DEVICE_ID}/ai-edge",
        json={
            "min_face_pixels": 80,
            "min_laplacian_variance": 45,
            "min_brightness": 25,
            "max_brightness": 235,
            "min_top1_similarity": None,
            "min_top1_top2_margin": None,
            "minimum_agreeing_frames": 3,
            "sample_every_n_frames": 5,
            "best_frame_count": 5,
            "max_history_frames": 10,
            "calibration_reference": None,
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["revision"] == 1
    assert result["apply_status"] == "pending"
    assert result["settings"]["min_top1_similarity"] is None
    assert result["settings"]["min_top1_top2_margin"] is None


def test_edge_thresholds_must_be_a_calibrated_pair(
    edge_settings_client: TestClient,
) -> None:
    response = edge_settings_client.put(
        f"/api/v1/admin/settings/devices/{DEVICE_ID}/ai-edge",
        json={
            "min_face_pixels": 80,
            "min_laplacian_variance": 45,
            "min_brightness": 25,
            "max_brightness": 235,
            "min_top1_similarity": 0.7,
            "min_top1_top2_margin": None,
            "minimum_agreeing_frames": 3,
            "sample_every_n_frames": 5,
            "best_frame_count": 5,
            "max_history_frames": 10,
            "calibration_reference": None,
        },
    )

    assert response.status_code == 422
