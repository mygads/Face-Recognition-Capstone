from __future__ import annotations

import asyncio
import base64
import json
import secrets
from collections.abc import Generator
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from presensi_api.api.security.device_credentials import hash_device_credential
from presensi_api.biometric_crypto import FaceTemplateKeyring
from presensi_api.db.base import Base
from presensi_api.db.models import (
    AttendanceRecord,
    AttendanceSession,
    ClassStudent,
    Device,
    FaceTemplate,
    Laboratory,
    PracticumSchedule,
    SchoolClass,
    SessionStudent,
    Student,
    User,
)
from presensi_api.db.session import get_db_session
from presensi_api.main import app

DEVICE_ID = UUID("91d79367-8f2a-479e-8ae2-b820f7a0e6f8")
OTHER_DEVICE_ID = UUID("b9773dfd-653e-457c-a9ce-55a818663aed")
SESSION_ID = UUID("66ce7510-7b21-43ea-ac92-9cefd1cdb785")
STUDENT_ID = UUID("53385b60-3765-49ee-8cd1-c5933da53507")
LAB_ID = UUID("0bcdbd9c-6328-4e39-8158-e0bb85e54210")
TOKEN = "t" + secrets.token_urlsafe(48)
MODEL_NAME = "opencv-zoo-sface"
MODEL_VERSION = "synthetic-v1"


@pytest.fixture
def runtime_database(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[sessionmaker[Session], dict[str, Any]], None, None]:
    monkeypatch.setenv(
        "PRESENSI_FACE_TEMPLATE_KEYS",
        json.dumps({"test-v1": base64.b64encode(b"d" * 32).decode("ascii")}),
    )
    monkeypatch.setenv("PRESENSI_FACE_TEMPLATE_ACTIVE_KEY_ID", "test-v1")
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
    now = datetime.now(UTC)
    local_now = now.astimezone(ZoneInfo("Asia/Jakarta"))
    start = time(0, 1)
    end = time(23, 59)
    opened_at = now - timedelta(minutes=2)
    teacher = User(
        id=uuid4(),
        email="teacher@example.test",
        full_name="Synthetic Teacher",
        password_hash="unused-test-hash",
    )
    school_class = SchoolClass(
        id=uuid4(),
        code="X-RUNTIME",
        name="Runtime Class",
        grade=10,
        academic_year="2026-2027",
    )
    laboratory = Laboratory(id=LAB_ID, code="LAB-RUNTIME", name="Runtime Lab")
    student = Student(
        id=STUDENT_ID,
        student_number="STUDENT-RUNTIME",
        full_name="Synthetic Runtime Student",
    )
    device = Device(
        id=DEVICE_ID,
        laboratory_id=LAB_ID,
        name="Runtime Edge",
        device_type="edge_pc",
        deployment_profile="AI_EDGE",
        credential_hash=hash_device_credential(TOKEN),
        credential_expires_at=now + timedelta(days=90),
    )
    schedule = PracticumSchedule(
        id=uuid4(),
        class_id=school_class.id,
        laboratory_id=LAB_ID,
        teacher_user_id=teacher.id,
        subject="Synthetic Practicum",
        weekday=local_now.weekday(),
        start_time=start,
        end_time=end,
        timezone_name="Asia/Jakarta",
        effective_from=local_now.date() - timedelta(days=1),
    )
    attendance_session = AttendanceSession(
        id=SESSION_ID,
        practicum_schedule_id=schedule.id,
        opened_by_user_id=teacher.id,
        status="active",
        opened_at=opened_at,
        grace_period_minutes=15,
    )
    with factory.begin() as session:
        session.add_all([teacher, school_class, laboratory, student, device, schedule])
        session.flush()
        session.add_all(
            [
                ClassStudent(class_id=school_class.id, student_id=student.id),
                attendance_session,
                SessionStudent(
                    session_id=SESSION_ID,
                    student_id=STUDENT_ID,
                    student_number_snapshot=student.student_number,
                    full_name_snapshot=student.full_name,
                    snapshot_taken_at=opened_at,
                ),
            ]
        )
        session.flush()
        keyring = FaceTemplateKeyring.from_environment()
        for vector in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)):
            template_id = uuid4()
            encrypted = keyring.encrypt(
                vector,
                template_id=template_id,
                student_id=STUDENT_ID,
                model_name=MODEL_NAME,
                model_version=MODEL_VERSION,
            )
            session.add(
                FaceTemplate(
                    id=template_id,
                    student_id=STUDENT_ID,
                    model_name=MODEL_NAME,
                    model_version=MODEL_VERSION,
                    embedding_ciphertext=encrypted.ciphertext,
                    encryption_key_id=encrypted.key_id,
                    embedding_dimension=encrypted.dimension,
                    quality_metadata={"score": 0.95},
                )
            )

    try:
        yield factory, {"now": now, "expires": now + timedelta(days=90)}
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _headers(device_id: UUID = DEVICE_ID, token: str = TOKEN) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Device-ID": str(device_id),
    }


def _request(
    method: str,
    path: str,
    *,
    device_id: UUID = DEVICE_ID,
    token: str = TOKEN,
    json_body: dict[str, object] | None = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.request(
                method,
                path,
                headers=_headers(device_id, token),
                json=json_body,
            )

    return asyncio.run(send())


def test_device_discovery_and_gallery_are_scoped_and_decrypted_on_demand(
    runtime_database: tuple[sessionmaker[Session], dict[str, Any]],
) -> None:
    sessions = _request("GET", f"/api/v1/devices/{DEVICE_ID}/active-sessions")
    assert sessions.status_code == 200
    assert len(sessions.json()) == 1
    assert sessions.json()[0]["session_id"] == str(SESSION_ID)

    gallery = _request(
        "GET",
        f"/api/v1/devices/{DEVICE_ID}/active-session-cache"
        f"?session_id={SESSION_ID}&model_name={MODEL_NAME}&model_version={MODEL_VERSION}",
    )

    assert gallery.status_code == 200, gallery.text
    payload = gallery.json()
    assert payload["roster"][0]["student_id"] == str(STUDENT_ID)
    assert len(payload["roster"][0]["templates"]) == 2
    assert payload["roster"][0]["templates"][0]["normalized"] is True
    assert payload["expires_at"] <= payload["session_ends_at"]
    assert "embedding_ciphertext" not in gallery.text
    assert "ciphertext" not in gallery.text

    wrong_device = _request(
        "GET",
        f"/api/v1/devices/{OTHER_DEVICE_ID}/active-sessions",
    )
    assert wrong_device.status_code == 403


def test_device_authentication_rejects_missing_or_unknown_credentials(
    runtime_database: tuple[sessionmaker[Session], dict[str, Any]],
) -> None:
    async def send_without_credentials() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get(
                f"/api/v1/devices/{DEVICE_ID}/active-sessions",
                headers={"X-Device-ID": str(DEVICE_ID)},
            )

    missing = asyncio.run(send_without_credentials())
    invalid = _request(
        "GET",
        f"/api/v1/devices/{DEVICE_ID}/active-sessions",
        token="wrong-device-token",
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_credential_renewal_returns_new_secret_and_accepts_short_overlap(
    runtime_database: tuple[sessionmaker[Session], dict[str, Any]],
) -> None:
    response = _request("POST", f"/api/v1/devices/{DEVICE_ID}/credentials/renew")

    assert response.status_code == 200, response.text
    new_token = response.json()["token"]
    assert new_token != TOKEN
    assert response.json()["previous_token_valid_until"] is not None
    assert (
        _request(
            "GET",
            f"/api/v1/devices/{DEVICE_ID}/active-sessions",
            token=TOKEN,
        ).status_code
        == 200
    )
    assert (
        _request(
            "GET",
            f"/api/v1/devices/{DEVICE_ID}/active-sessions",
            token=new_token,
        ).status_code
        == 200
    )
    with runtime_database[0]() as session:
        device = session.get(Device, DEVICE_ID)
        assert device is not None
        assert device.credential_hash == hash_device_credential(new_token)
        assert device.credential_hash != new_token


def test_device_event_uses_shared_attendance_decision_and_is_idempotent(
    runtime_database: tuple[sessionmaker[Session], dict[str, Any]],
) -> None:
    event_id = uuid4()
    payload: dict[str, object] = {
        "event_id": str(event_id),
        "device_id": str(DEVICE_ID),
        "session_id": str(SESSION_ID),
        "student_id": str(STUDENT_ID),
        "outcome": "matched",
        "similarity": 0.93,
        "occurred_at": datetime.now(UTC).isoformat(),
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
    }

    first = _request(
        "POST",
        f"/api/v1/devices/{DEVICE_ID}/recognition-events",
        json_body=payload,
    )
    retry = _request(
        "POST",
        f"/api/v1/devices/{DEVICE_ID}/recognition-events",
        json_body=payload,
    )

    assert first.status_code == 200, first.text
    assert first.json()["decision"] == "attendance_recorded"
    assert retry.status_code == 200
    assert retry.json()["replayed"] is True
    with runtime_database[0]() as session:
        records = session.scalars(
            select(AttendanceRecord).where(
                AttendanceRecord.session_id == SESSION_ID,
                AttendanceRecord.student_id == STUDENT_ID,
            )
        ).all()
        assert len(records) == 1
