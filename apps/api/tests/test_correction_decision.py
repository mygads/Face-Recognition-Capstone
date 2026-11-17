from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime, time
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from presensi_api.api.security.dependencies import get_current_user
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
from presensi_api.db.base import Base
from presensi_api.db.models import (
    AttendanceRecord,
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

TEACHER_ID = UUID(int=1101)
ADMIN_ID = UUID(int=1102)
OTHER_TEACHER_ID = UUID(int=1103)


@pytest.fixture
def correction_database() -> Generator[
    tuple[sessionmaker[Session], dict[str, UUID]], None, None
]:
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
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=TEACHER_ID,
        email="teacher@example.test",
        full_name="Synthetic Teacher",
        roles=frozenset({RoleCode.TEACHER}),
    )

    local_now = datetime.now(ZoneInfo("Asia/Jakarta"))
    with factory.begin() as db:
        teacher = User(
            id=TEACHER_ID,
            email="teacher@example.test",
            full_name="Synthetic Teacher",
            password_hash="unused-test-hash",
        )
        admin = User(
            id=ADMIN_ID,
            email="admin@example.test",
            full_name="Synthetic Admin",
            password_hash="unused-test-hash",
        )
        other_teacher = User(
            id=OTHER_TEACHER_ID,
            email="other@example.test",
            full_name="Other Teacher",
            password_hash="unused-test-hash",
        )
        school_class = SchoolClass(
            code="X-C", name="Synthetic Class", grade=10, academic_year="2026-2027"
        )
        laboratory = Laboratory(code="LAB-C", name="Lab C")
        first = Student(student_number="C-001", full_name="Siswa Satu")
        db.add_all([teacher, admin, other_teacher, school_class, laboratory, first])
        db.flush()
        schedule = PracticumSchedule(
            class_id=school_class.id,
            laboratory_id=laboratory.id,
            teacher_user_id=teacher.id,
            subject="Synthetic Practicum",
            weekday=local_now.weekday(),
            start_time=time(0, 0),
            end_time=time(23, 59),
            timezone_name="Asia/Jakarta",
            effective_from=local_now.date(),
            effective_through=local_now.date(),
        )
        db.add(schedule)
        db.flush()
        db.add(ClassStudent(class_id=school_class.id, student_id=first.id))
        opened_at = datetime.now(UTC)
        attendance_session = AttendanceSession(
            practicum_schedule_id=schedule.id,
            opened_by_user_id=teacher.id,
            status="manual_override",
            opened_at=opened_at,
            grace_period_minutes=15,
        )
        db.add(attendance_session)
        db.flush()
        db.add(
            SessionStudent(
                session_id=attendance_session.id,
                student_id=first.id,
                student_number_snapshot=first.student_number,
                full_name_snapshot=first.full_name,
                snapshot_taken_at=opened_at,
            )
        )
        db.flush()
        db.add(
            AttendanceRecord(
                session_id=attendance_session.id,
                student_id=first.id,
                status="present",
                source="manual",
                recognition_event_id=None,
                recorded_at=opened_at,
                recorded_by_user_id=teacher.id,
            )
        )
        ids = {
            "schedule": schedule.id,
            "session": attendance_session.id,
            "student": first.id,
        }
    yield factory, ids
    app.dependency_overrides.clear()
    engine.dispose()


def use_role(role: RoleCode, user_id: UUID) -> None:
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=user_id,
        email=f"{role.value.lower()}@example.test",
        full_name=f"Synthetic {role.value}",
        roles=frozenset({role}),
    )


def api_post(path: str, body: dict[str, object] | None) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.post(path, json=body)

    return asyncio.run(send())


def api_get(path: str) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get(path)

    return asyncio.run(send())


def test_correction_endpoints_are_gone(
    correction_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    """Fitur koreksi dihapus: endpoint lama tidak lagi ada (404 route)."""
    _, ids = correction_database
    use_role(RoleCode.TEACHER, TEACHER_ID)
    assert (
        api_post("/api/v1/attendance/corrections", {"reason": "x"}).status_code == 404
    )
    assert api_get("/api/v1/attendance/corrections").status_code == 404
    assert (
        api_post(
            f"/api/v1/attendance/corrections/{UUID(int=9)}/decision",
            {"decision": "approved"},
        ).status_code
        == 404
    )


def test_teacher_updates_record_directly_without_correction(
    correction_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    """Guru/aslab berwenang langsung memperbarui catatan tanpa admin."""
    factory, ids = correction_database
    use_role(RoleCode.TEACHER, TEACHER_ID)
    updated = api_post(
        f"/api/v1/attendance/sessions/{ids['session']}/manual-marks",
        {"student_id": str(ids["student"]), "status": "late", "note": "ralat langsung"},
    )
    assert updated.status_code == 201, updated.text
    assert updated.json()["record"]["status"] == "late"
    with factory() as session:
        audit = session.scalar(
            select(AuditLog).where(
                AuditLog.action == "attendance.manual_updated",
                AuditLog.actor_user_id == TEACHER_ID,
            )
        )
        assert audit is not None
