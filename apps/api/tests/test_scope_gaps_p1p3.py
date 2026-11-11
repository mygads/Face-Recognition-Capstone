"""Regresi gap audit P1/P3: light snapshot, rotate+TTL, scope detail lab,
laboran kelola jadwal, minutes_late dari occurred_at."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from datetime import time as dtime
from uuid import UUID

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from presensi_api.api.security.config import AuthSettings
from presensi_api.api.security.dependencies import (
    decode_display_token,
    get_auth_settings,
    get_current_user,
    issue_display_token,
)
from presensi_api.api.security.passwords import hash_password
from presensi_api.api.security.roles import AuthenticatedUser, Permission, RoleCode
from presensi_api.db.base import Base
from presensi_api.db.models import (
    AttendanceRecord,
    AttendanceSession,
    LaborantLabAssignment,
    Laboratory,
    PracticumSchedule,
    Role,
    SchoolClass,
    SessionStudent,
    Student,
    User,
    UserRole,
)
from presensi_api.db.seed_roles import seed_roles
from presensi_api.db.session import get_db_session
from presensi_api.main import app

TEST_SETTINGS = AuthSettings(signing_secret="z" * 40)
TEACHER_ID = UUID(int=43)
LABORAN_ID = UUID(int=77)


@pytest.fixture
def gap_database() -> Generator[sessionmaker[Session], None, None]:
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
    admin = AuthenticatedUser(
        id=UUID(int=42),
        email="admin@example.test",
        full_name="Test Admin",
        roles=frozenset({RoleCode.ADMIN}),
    )
    app.dependency_overrides[get_current_user] = lambda: admin
    with factory.begin() as session:
        seed_roles(session)
        from sqlalchemy import select as _select

        teacher_role = session.scalar(_select(Role).where(Role.code == "TEACHER"))
        assert teacher_role is not None
        teacher = User(
            id=TEACHER_ID,
            email="teacher@example.test",
            full_name="Test Teacher",
            password_hash="unused-test-hash",
        )
        laboran = User(
            id=LABORAN_ID,
            email="laboran@example.test",
            full_name="Test Laboran",
            password_hash="unused-test-hash",
        )
        session.add_all([teacher, laboran])
        session.flush()
        session.add(UserRole(user_id=teacher.id, role_id=teacher_role.id))
        lab_a = Laboratory(
            code="LAB-A", name="Lab A", display_pin_hash=hash_password("1234")
        )
        lab_b = Laboratory(code="LAB-B", name="Lab B")
        session.add_all([lab_a, lab_b])
        session.flush()
        session.add(LaborantLabAssignment(user_id=laboran.id, laboratory_id=lab_a.id))
        class_a = SchoolClass(
            code="X-A", name="Kelas X A", grade=10, academic_year="2026-2027"
        )
        session.add(class_a)
        session.flush()
        schedule = PracticumSchedule(
            class_id=class_a.id,
            laboratory_id=lab_a.id,
            teacher_user_id=teacher.id,
            subject="Kimia",
            weekday=0,
            start_time=dtime(9, 0),
            end_time=dtime(10, 0),
            timezone_name="Asia/Jakarta",
            effective_from=datetime.now(UTC).date(),
            is_active=True,
        )
        session.add(schedule)
        session.flush()
        opened_at = datetime.now(UTC).replace(microsecond=0)
        att_session = AttendanceSession(
            practicum_schedule_id=schedule.id,
            opened_by_user_id=teacher.id,
            status="active",
            opened_at=opened_at,
        )
        session.add(att_session)
        session.flush()
        students = [
            Student(student_number="S-001", full_name="Satu"),
            Student(student_number="S-002", full_name="Dua"),
            Student(student_number="S-003", full_name="Tiga"),
        ]
        session.add_all(students)
        session.flush()
        for number, name in (("S-001", "Satu"), ("S-002", "Dua"), ("S-003", "Tiga")):
            student = next(s for s in students if s.student_number == number)
            session.add(
                SessionStudent(
                    session_id=att_session.id,
                    student_id=student.id,
                    student_number_snapshot=number,
                    full_name_snapshot=name,
                )
            )
        # S-001: datang +10 mnt, dicatat +50 mnt -> telat 10, bukan 50.
        s1 = next(s for s in students if s.student_number == "S-001")
        session.add(
            AttendanceRecord(
                session_id=att_session.id,
                student_id=s1.id,
                status="late",
                source="manual",
                recognition_event_id=None,
                recorded_at=opened_at + timedelta(minutes=50),
                occurred_at=opened_at + timedelta(minutes=10),
            )
        )
        # S-002: telat tanpa waktu datang -> minutes_late None (jangan dikarang).
        s2 = next(s for s in students if s.student_number == "S-002")
        session.add(
            AttendanceRecord(
                session_id=att_session.id,
                student_id=s2.id,
                status="late",
                source="manual",
                recognition_event_id=None,
                recorded_at=opened_at + timedelta(minutes=50),
                occurred_at=None,
            )
        )
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


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


def _set_principal(
    user_id: UUID, roles: frozenset[RoleCode], extra: frozenset[Permission]
) -> None:
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=user_id,
        email=f"user{user_id.int}@example.test",
        full_name="Test Principal",
        roles=roles,
        extra_permissions=extra,
    )


def _lab_ids(factory: sessionmaker[Session]) -> tuple[str, str]:
    with factory() as session:
        from sqlalchemy import select

        rows = session.scalars(select(Laboratory).order_by(Laboratory.code)).all()
        return str(rows[0].id), str(rows[1].id)


def test_display_light_mode_and_rotate(gap_database: sessionmaker[Session]) -> None:
    lab_a, _ = _lab_ids(gap_database)
    opened = request(
        "POST",
        "/api/v1/public/display/session",
        {"laboratory_id": lab_a, "pin": "1234", "light": True},
    )
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert body["snapshot"]["students"] == []
    assert body["snapshot"]["total_roster"] == 3
    assert body["expires_in_seconds"] == 8 * 3600
    token = body["display_token"]

    full = request("GET", f"/api/v1/public/display?token={token}")
    assert full.status_code == 200, full.text
    assert len(full.json()["students"]) == 3

    light = request("GET", f"/api/v1/public/display?token={token}&light=true")
    assert light.status_code == 200, light.text
    assert light.json()["students"] == []
    assert light.json()["total_roster"] == 3

    rotated = request("POST", "/api/v1/public/display/rotate", {"display_token": token})
    assert rotated.status_code == 200, rotated.text
    new_body = rotated.json()
    assert new_body["display_token"] != token
    claims = decode_display_token(new_body["display_token"], TEST_SETTINGS)
    assert claims is not None and claims.kind == "lab"
    assert str(claims.laboratory_id) == lab_a
    assert new_body["snapshot"]["students"] == []

    bad = request("POST", "/api/v1/public/display/rotate", {"display_token": "salah"})
    assert bad.status_code in (401, 422), bad.text
    cross = request(
        "POST", "/api/v1/public/kiosk-display/rotate", {"display_token": token}
    )
    assert cross.status_code == 401, cross.text


def test_issue_display_token_ttl_is_eight_hours() -> None:
    _, ttl = issue_display_token("lab", UUID(int=1), UUID(int=2), TEST_SETTINGS)
    assert ttl == 8 * 3600


def test_laboratory_detail_scoped_for_laboran(
    gap_database: sessionmaker[Session],
) -> None:
    lab_a, lab_b = _lab_ids(gap_database)
    _set_principal(LABORAN_ID, frozenset({RoleCode.LABORANT}), frozenset())
    assert request("GET", f"/api/v1/laboratories/{lab_a}").status_code == 200
    resp = request("GET", f"/api/v1/laboratories/{lab_b}")
    assert resp.status_code == 404, resp.text


def test_laboran_schedule_manage_scoped_to_assigned_labs(
    gap_database: sessionmaker[Session],
) -> None:
    lab_a, lab_b = _lab_ids(gap_database)
    with gap_database() as session:
        from sqlalchemy import select

        class_id = str(session.scalars(select(SchoolClass)).one().id)
    _set_principal(
        LABORAN_ID,
        frozenset({RoleCode.LABORANT}),
        frozenset({Permission.SCHEDULE_MANAGE}),
    )
    ok_payload = {
        "class_id": class_id,
        "laboratory_id": lab_a,
        "teacher_user_id": str(TEACHER_ID),
        "subject": "Fisika",
        "weekday": 2,
        "start_time": "09:00",
        "end_time": "10:00",
        "timezone_name": "Asia/Jakarta",
        "effective_from": "2026-09-01",
    }
    created = request("POST", "/api/v1/schedules", ok_payload)
    assert created.status_code == 201, created.text

    other_payload = {**ok_payload, "laboratory_id": lab_b}
    denied = request("POST", "/api/v1/schedules", other_payload)
    assert denied.status_code == 403, denied.text


def test_autoclose_session_opened_after_schedule_end(
    gap_database: sessionmaker[Session],
) -> None:
    """Sesi yang dibuka setelah jam berakhir tetap bisa dibaca.

    Auto-close pada GET roster tidak boleh 500 karena closed_at mundur
    sebelum opened_at (CHECK ..._close_after_open); closed_at dijepit ke
    opened_at dan sesi ditutup saat itu juga.
    """
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    with gap_database.begin() as session:
        lab = session.scalars(
            select(Laboratory).where(Laboratory.code == "LAB-A")
        ).one()
        class_a = session.scalars(select(SchoolClass)).one()
        teacher = session.scalars(select(User).where(User.id == TEACHER_ID)).one()
        wib_now = datetime.now(UTC).astimezone(ZoneInfo("Asia/Jakarta"))
        ended = (wib_now - timedelta(hours=1)).time().replace(microsecond=0)
        schedule = PracticumSchedule(
            class_id=class_a.id,
            laboratory_id=lab.id,
            teacher_user_id=teacher.id,
            subject="Kimia Susulan",
            weekday=wib_now.weekday(),
            start_time=(wib_now - timedelta(hours=2)).time().replace(microsecond=0),
            end_time=ended,
            timezone_name="Asia/Jakarta",
            effective_from=wib_now.date(),
            is_active=True,
        )
        session.add(schedule)
        session.flush()
        opened_at = datetime.now(UTC).replace(microsecond=0)
        att_session = AttendanceSession(
            practicum_schedule_id=schedule.id,
            opened_by_user_id=teacher.id,
            status="active",
            opened_at=opened_at,
        )
        session.add(att_session)
        session.flush()
        session_id = str(att_session.id)
    _set_principal(TEACHER_ID, frozenset({RoleCode.TEACHER}), frozenset())
    roster = request("GET", f"/api/v1/sessions/{session_id}/roster")
    assert roster.status_code == 200, roster.text
    with gap_database() as session:
        row = session.scalars(
            select(AttendanceSession).where(AttendanceSession.id == UUID(session_id))
        ).one()
        assert row.status == "closed"
        assert row.closed_at is not None
        assert row.closed_at >= row.opened_at


def test_minutes_late_uses_occurred_at(gap_database: sessionmaker[Session]) -> None:
    with gap_database() as session:
        from sqlalchemy import select

        session_id = str(session.scalars(select(AttendanceSession)).one().id)
    _set_principal(
        LABORAN_ID,
        frozenset({RoleCode.LABORANT}),
        frozenset({Permission.SESSION_VIEW}),
    )
    roster = request("GET", f"/api/v1/sessions/{session_id}/roster")
    assert roster.status_code == 200, roster.text
    by_number = {entry["student_number"]: entry for entry in roster.json()}
    assert by_number["S-001"]["minutes_late"] == 10
    assert by_number["S-002"]["minutes_late"] is None
