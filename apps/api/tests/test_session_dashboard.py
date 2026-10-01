from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.websockets import WebSocketDisconnect

from presensi_api.api.security.config import AuthSettings
from presensi_api.api.security.dependencies import get_current_user, issue_access_token
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
from presensi_api.db.base import Base
from presensi_api.db.models import (
    AttendanceRecord,
    AttendanceSession,
    Device,
    Laboratory,
    PracticumSchedule,
    RecognitionEvent,
    Role,
    SchoolClass,
    SessionStudent,
    Student,
    User,
    UserRole,
)
from presensi_api.db.session import get_db_session
from presensi_api.main import app


@pytest.fixture
def dashboard_database(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[sessionmaker[Session], dict[str, UUID]], None, None]:
    monkeypatch.setenv("JWT_SECRET", "session-dashboard-test-secret-000000")
    monkeypatch.setenv("SESSION_DASHBOARD_POLL_SECONDS", "0.25")
    monkeypatch.setattr("presensi_api.main._run_session_auto_close_sweep", lambda: None)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    admin = AuthenticatedUser(
        id=UUID(int=9401),
        email="admin@example.test",
        full_name="Synthetic Admin",
        roles=frozenset({RoleCode.ADMIN}),
    )
    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user] = lambda: admin

    local_now = datetime.now(ZoneInfo("Asia/Jakarta"))
    with factory.begin() as db:
        user = User(
            id=admin.id,
            email=admin.email,
            full_name=admin.full_name,
            password_hash="unused-test-hash",
        )
        role = Role(code="ADMIN", name="Administrator")
        school_class = SchoolClass(
            code="X-TEST",
            name="Kelas Uji",
            grade=10,
            academic_year="2026-2027",
        )
        laboratory = Laboratory(code="LAB-TEST", name="Lab Uji")
        students = [
            Student(student_number=f"S-{index:03}", full_name=f"Siswa {index}")
            for index in range(1, 4)
        ]
        db.add_all([user, role, school_class, laboratory, *students])
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=role.id))
        schedule = PracticumSchedule(
            class_id=school_class.id,
            laboratory_id=laboratory.id,
            teacher_user_id=user.id,
            subject="Praktikum Uji",
            weekday=local_now.weekday(),
            start_time=time(0, 0),
            end_time=time(23, 59, 59),
            timezone_name="Asia/Jakarta",
            effective_from=local_now.date(),
            effective_through=local_now.date(),
        )
        device = Device(
            laboratory_id=laboratory.id,
            name="Kamera Lab Uji",
            device_type="edge_pc",
            last_seen_at=datetime.now(UTC),
        )
        db.add_all([schedule, device])
        db.flush()
        attendance_session = AttendanceSession(
            practicum_schedule_id=schedule.id,
            opened_by_user_id=user.id,
            status="active",
            opened_at=datetime.now(UTC),
            grace_period_minutes=15,
        )
        db.add(attendance_session)
        db.flush()
        db.add_all(
            [
                SessionStudent(
                    session_id=attendance_session.id,
                    student_id=student.id,
                    student_number_snapshot=student.student_number,
                    full_name_snapshot=student.full_name,
                )
                for student in students
            ]
        )
        recognition = RecognitionEvent(
            event_uuid=UUID(int=9402),
            session_id=attendance_session.id,
            device_id=device.id,
            recognized_student_id=students[0].id,
            occurred_at=datetime.now(UTC),
            outcome="matched",
            model_name="synthetic-model",
            model_version="test-1",
            confidence="0.99",
            similarity="0.88",
            margin="0.10",
            quality_metadata={"attendance_decision": {"status": "present"}},
        )
        db.add(recognition)
        db.flush()
        db.add(
            AttendanceRecord(
                session_id=attendance_session.id,
                student_id=students[0].id,
                recognition_event_id=recognition.id,
                status="present",
                source="face_recognition",
            )
        )
        ids = {
            "admin": user.id,
            "role": role.id,
            "session": attendance_session.id,
            "device": device.id,
            "present_student": students[0].id,
            "late_student": students[1].id,
            "absent_student": students[2].id,
        }

    yield factory, ids
    app.dependency_overrides.clear()
    engine.dispose()


def access_token(*, now: datetime | None = None) -> str:
    settings = AuthSettings(signing_secret="session-dashboard-test-secret-000000")
    token, _ = issue_access_token(UUID(int=9401), settings, now=now)
    return token


def test_websocket_sends_safe_snapshot_and_updates_attendance_live(
    dashboard_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    factory, ids = dashboard_database
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/sessions/{ids['session']}/updates"
        ) as websocket:
            websocket.send_json(
                {"type": "authenticate", "access_token": access_token()}
            )
            first_message = websocket.receive_json()
            assert first_message["type"] == "snapshot"
            first = first_message["data"]
            assert first["summary"] == {
                "total_roster": 3,
                "present": 1,
                "late": 0,
                "not_present": 2,
            }
            assert first["recent_activity"][0]["student_name"] == "Siswa 1"
            assert first["devices"][0]["is_online"] is True
            assert not {"embedding", "image", "photo", "blob"} & set(first)

            with factory.begin() as db:
                db.add(
                    AttendanceRecord(
                        session_id=ids["session"],
                        student_id=ids["late_student"],
                        status="late",
                        source="manual",
                        recorded_at=datetime.now(UTC) + timedelta(seconds=1),
                    )
                )

            updated_message = websocket.receive_json()
            updated = updated_message["data"]
            assert updated["summary"] == {
                "total_roster": 3,
                "present": 1,
                "late": 1,
                "not_present": 1,
            }
            assert updated["recent_activity"][0]["student_name"] == "Siswa 2"
            assert updated["recent_activity"][0]["attendance_status"] == "late"
            assert "embedding" not in str(updated).lower()
            assert "image" not in str(updated).lower()


def test_device_heartbeat_marks_device_online_in_dashboard(
    dashboard_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    factory, ids = dashboard_database
    with factory.begin() as db:
        device = db.get(Device, ids["device"])
        assert device is not None
        device.last_seen_at = datetime.now(UTC) - timedelta(minutes=5)

    with TestClient(app) as client:
        response = client.post(f"/api/v1/devices/{ids['device']}/heartbeat")
        assert response.status_code == 200
        assert response.json()["device_id"] == str(ids["device"])
        with client.websocket_connect(
            f"/api/v1/sessions/{ids['session']}/updates"
        ) as websocket:
            websocket.send_json(
                {"type": "authenticate", "access_token": access_token()}
            )
            snapshot = websocket.receive_json()["data"]
            assert snapshot["devices"][0]["is_online"] is True


def test_websocket_rejects_invalid_authentication(
    dashboard_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    _, ids = dashboard_database
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as disconnected:
            with client.websocket_connect(
                f"/api/v1/sessions/{ids['session']}/updates"
            ) as websocket:
                websocket.send_json(
                    {"type": "authenticate", "access_token": "invalid-token"}
                )
                websocket.receive_json()
    assert disconnected.value.code == 4401


def test_websocket_rejects_expired_access_token(
    dashboard_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    _, ids = dashboard_database
    expired_token = access_token(now=datetime.now(UTC) - timedelta(hours=1))
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as disconnected:
            with client.websocket_connect(
                f"/api/v1/sessions/{ids['session']}/updates"
            ) as websocket:
                websocket.send_json(
                    {"type": "authenticate", "access_token": expired_token}
                )
                websocket.receive_json()
    assert disconnected.value.code == 4401
