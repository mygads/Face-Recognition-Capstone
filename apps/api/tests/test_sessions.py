from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from presensi_api.api.security.dependencies import get_current_user
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
from presensi_api.db.base import Base
from presensi_api.db.models import (
    AttendanceSession,
    AuditLog,
    ClassStudent,
    Laboratory,
    PracticumSchedule,
    SchoolClass,
    SessionStudent,
    Student,
    User,
)
from presensi_api.db.session import get_db_session
from presensi_api.main import app
from presensi_api.session_lifecycle import (
    auto_open_due_sessions,
    close_expired_sessions,
    scheduled_end_at,
)

ADMIN_ID = UUID(int=44)


@pytest.fixture
def api_database() -> Generator[sessionmaker[Session], None, None]:
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

    app.dependency_overrides[get_db_session] = override_db
    principal = AuthenticatedUser(
        id=UUID(int=43),
        email="teacher@example.test",
        full_name="Test Teacher",
        roles=frozenset({RoleCode.TEACHER}),
    )
    app.dependency_overrides[get_current_user] = lambda: principal
    timezone = ZoneInfo("Asia/Jakarta")
    now_local = datetime.now(timezone)
    current_date = now_local.date()
    with factory.begin() as session:
        teacher = User(
            id=principal.id,
            email=principal.email,
            full_name=principal.full_name,
            password_hash="unused-test-hash",
        )
        admin = User(
            id=ADMIN_ID,
            email="admin@example.test",
            full_name="Test Admin",
            password_hash="unused-test-hash",
        )
        school_class = SchoolClass(
            code="X-A",
            name="Kelas X A",
            grade=10,
            academic_year="2026-2027",
        )
        first = Student(student_number="S-001", full_name="Siswa Satu")
        second = Student(student_number="S-002", full_name="Siswa Dua")
        session.add_all([teacher, admin, school_class, first, second])
        session.flush()
        schedule = PracticumSchedule(
            class_id=school_class.id,
            laboratory_id=make_laboratory(session).id,
            teacher_user_id=teacher.id,
            subject="Praktikum Sintetis",
            weekday=now_local.weekday(),
            start_time=time(0, 0),
            end_time=time(23, 59),
            timezone_name="Asia/Jakarta",
            effective_from=current_date,
            effective_through=current_date,
        )
        session.add(schedule)
        session.flush()
        session.add_all(
            [
                ClassStudent(class_id=school_class.id, student_id=first.id),
                ClassStudent(class_id=school_class.id, student_id=second.id),
            ]
        )
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


def make_laboratory(session: Session) -> Laboratory:
    laboratory = Laboratory(code="LAB-1", name="Lab Biologi")
    session.add(laboratory)
    session.flush()
    return laboratory


def request(
    method: str,
    path: str,
    body: dict[str, object] | None = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.request(method, path, json=body)

    return asyncio.run(send())


def schedule_id(factory: sessionmaker[Session]) -> UUID:
    with factory() as session:
        schedule = session.scalars(select(PracticumSchedule)).first()
        assert schedule is not None
        return schedule.id


def test_open_session_snapshots_roster_and_closes_manually(
    api_database: sessionmaker[Session],
) -> None:
    practicum_schedule_id = schedule_id(api_database)
    missing = request("GET", f"/api/v1/sessions/{UUID(int=800)}")
    assert missing.status_code == 404

    opened = request(
        "POST",
        "/api/v1/sessions",
        {
            "practicum_schedule_id": str(practicum_schedule_id),
            "grace_period_minutes": 7,
        },
    )
    assert opened.status_code == 201
    session_data = opened.json()
    session_id = session_data["id"]
    assert session_data["status"] == "active"
    assert session_data["grace_period_minutes"] == 7
    assert session_data["student_count"] == 2

    with api_database.begin() as session:
        snapshot = session.scalars(
            select(SessionStudent)
            .where(SessionStudent.session_id == UUID(session_id))
            .order_by(SessionStudent.student_number_snapshot)
        ).all()
        assert [
            (item.student_number_snapshot, item.full_name_snapshot) for item in snapshot
        ] == [
            ("S-001", "Siswa Satu"),
            ("S-002", "Siswa Dua"),
        ]
        added_student = Student(student_number="S-003", full_name="Siswa Tiga")
        session.add(added_student)
        session.flush()
        schedule = session.get(PracticumSchedule, practicum_schedule_id)
        assert schedule is not None
        session.add(
            ClassStudent(class_id=schedule.class_id, student_id=added_student.id)
        )

    duplicate_open = request(
        "POST",
        "/api/v1/sessions",
        {"practicum_schedule_id": str(practicum_schedule_id)},
    )
    assert duplicate_open.status_code == 409
    assert duplicate_open.json()["error"]["code"] == "session_already_active"

    status_response = request("GET", f"/api/v1/sessions/{session_id}")
    assert status_response.status_code == 200
    assert status_response.json()["student_count"] == 2

    closed = request("POST", f"/api/v1/sessions/{session_id}/close")
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    closed_again = request("POST", f"/api/v1/sessions/{session_id}/close")
    assert closed_again.status_code == 200
    assert closed_again.json()["status"] == "closed"


def test_session_grace_period_defaults_to_fifteen_minutes(
    api_database: sessionmaker[Session],
) -> None:
    opened = request(
        "POST",
        "/api/v1/sessions",
        {"practicum_schedule_id": str(schedule_id(api_database))},
    )
    assert opened.status_code == 201
    assert opened.json()["grace_period_minutes"] == 15


def test_session_opening_policy_is_admin_managed_and_auto_opens_once(
    api_database: sessionmaker[Session],
) -> None:
    current = request(
        "GET",
        "/api/v1/sessions/policy",
    )
    assert current.status_code == 200
    assert current.json()["mode"] == "manual"
    assert current.json()["auto_open_minutes_before"] == 0
    assert current.json()["auto_open_minutes_after"] == 15

    policy_payload = {
        "mode": "automatic",
        "auto_open_minutes_before": 0,
        "auto_open_minutes_after": 15,
        "default_grace_period_minutes": 12,
    }
    denied = request("PUT", "/api/v1/sessions/policy", policy_payload)
    assert denied.status_code == 403

    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=ADMIN_ID,
        email="admin@example.test",
        full_name="Test Admin",
        roles=frozenset({RoleCode.ADMIN}),
    )
    published = request("PUT", "/api/v1/sessions/policy", policy_payload)
    assert published.status_code == 200, published.text
    assert published.json()["revision"] == 1

    automatic = request("GET", "/api/v1/sessions/openable-schedules")
    assert automatic.status_code == 200
    assert automatic.json() == []

    now = datetime(2026, 10, 5, 2, 5, tzinfo=UTC)  # Monday 09:05 in Jakarta.
    with api_database.begin() as session:
        schedule = session.scalars(select(PracticumSchedule)).one()
        schedule.weekday = 0
        schedule.start_time = time(9, 0)
        schedule.end_time = time(11, 0)
        schedule.timezone_name = "Asia/Jakarta"
        schedule.effective_from = now.astimezone(ZoneInfo("Asia/Jakarta")).date()
        schedule.effective_through = None

    with api_database() as session:
        assert (
            auto_open_due_sessions(
                session,
                policy=policy_payload,
                now=now,
            )
            == 1
        )
    with api_database() as session:
        opened = session.scalars(
            select(AttendanceSession).where(AttendanceSession.status == "active")
        ).one()
        assert opened.opened_by_user_id is None
        assert opened.grace_period_minutes == 12
        assert (
            session.scalar(
                select(func.count())
                .select_from(SessionStudent)
                .where(SessionStudent.session_id == opened.id)
            )
            == 2
        )
        auto_audit = session.scalar(
            select(AuditLog).where(
                AuditLog.action == "attendance_session.opened_automatically"
            )
        )
        assert auto_audit is not None

    with api_database() as session:
        assert (
            auto_open_due_sessions(
                session,
                policy=policy_payload,
                now=now + timedelta(minutes=1),
            )
            == 0
        )


def test_session_auto_closes_at_local_schedule_end(
    api_database: sessionmaker[Session],
) -> None:
    opened = request(
        "POST",
        "/api/v1/sessions",
        {"practicum_schedule_id": str(schedule_id(api_database))},
    )
    assert opened.status_code == 201
    session_id = UUID(opened.json()["id"])
    with api_database() as session:
        attendance_session = session.get(AttendanceSession, session_id)
        practicum_schedule_id = schedule_id(api_database)
        schedule = session.get(PracticumSchedule, practicum_schedule_id)
        assert attendance_session is not None and schedule is not None
        end_at = scheduled_end_at(schedule, attendance_session.opened_at)

    with api_database() as session:
        assert close_expired_sessions(session, now=end_at + timedelta(seconds=1)) == 1
        attendance_session = session.get(AttendanceSession, session_id)
        assert attendance_session is not None
        assert attendance_session.status == "closed"
        assert attendance_session.closed_at is not None
        assert attendance_session.closed_at.replace(tzinfo=UTC) == end_at

    current = request("GET", f"/api/v1/sessions/{session_id}")
    assert current.status_code == 200
    assert current.json()["status"] == "closed"
