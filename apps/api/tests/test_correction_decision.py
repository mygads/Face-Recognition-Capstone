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


def request_correction(record_id: UUID) -> httpx.Response:
    return api_post(
        "/api/v1/attendance/corrections",
        {
            "attendance_record_id": str(record_id),
            "corrected_status": "late",
            "reason": "Synthetic correction case",
        },
    )


def test_approve_updates_record_and_audit(
    correction_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    factory, ids = correction_database
    with factory() as db:
        record = db.scalar(select(AttendanceRecord))
        assert record is not None
        record_id = record.id
    use_role(RoleCode.TEACHER, TEACHER_ID)
    created = request_correction(record_id)
    assert created.status_code == 201, created.text
    correction_id = created.json()["id"]
    assert created.json()["decision_status"] == "pending"

    # Teacher must not be able to decide.
    forbidden = api_post(
        f"/api/v1/attendance/corrections/{correction_id}/decision",
        {"decision": "approved"},
    )
    assert forbidden.status_code == 403, forbidden.text

    use_role(RoleCode.ADMIN, ADMIN_ID)
    decided = api_post(
        f"/api/v1/attendance/corrections/{correction_id}/decision",
        {"decision": "approved", "decision_note": "  Disetujui  "},
    )
    assert decided.status_code == 200, decided.text
    body = decided.json()
    assert body["decision_status"] == "approved"
    assert body["decided_by_user_id"] == str(ADMIN_ID)
    assert body["decision_note"] == "Disetujui"
    assert body["decided_at"] is not None

    with factory() as db:
        stored_record = db.get(AttendanceRecord, record_id)
        assert stored_record is not None
        assert stored_record.status == "late"
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "attendance.correction.decided",
                AuditLog.entity_id == UUID(correction_id),
            )
        )
        assert audit is not None
        assert audit.actor_user_id == ADMIN_ID

    # Second decision must conflict.
    again = api_post(
        f"/api/v1/attendance/corrections/{correction_id}/decision",
        {"decision": "rejected"},
    )
    assert again.status_code == 409, again.text


def test_reject_leaves_record_unchanged(
    correction_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    factory, _ = correction_database
    with factory() as db:
        record = db.scalar(select(AttendanceRecord))
        assert record is not None
        record_id = record.id
    use_role(RoleCode.TEACHER, TEACHER_ID)
    created = request_correction(record_id)
    assert created.status_code == 201, created.text
    correction_id = created.json()["id"]

    use_role(RoleCode.ADMIN, ADMIN_ID)
    decided = api_post(
        f"/api/v1/attendance/corrections/{correction_id}/decision",
        {"decision": "rejected", "decision_note": "Bukti kurang"},
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["decision_status"] == "rejected"

    with factory() as db:
        stored_record = db.get(AttendanceRecord, record_id)
        assert stored_record is not None
        assert stored_record.status == "present"


def test_decision_rejects_stale_record(
    correction_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    factory, _ = correction_database
    with factory() as db:
        record = db.scalar(select(AttendanceRecord))
        assert record is not None
        record_id = record.id
    use_role(RoleCode.TEACHER, TEACHER_ID)
    created = request_correction(record_id)
    assert created.status_code == 201, created.text
    correction_id = created.json()["id"]

    with factory.begin() as db:
        stored = db.get(AttendanceRecord, record_id)
        assert stored is not None
        stored.status = "excused"

    use_role(RoleCode.ADMIN, ADMIN_ID)
    decided = api_post(
        f"/api/v1/attendance/corrections/{correction_id}/decision",
        {"decision": "approved"},
    )
    assert decided.status_code == 409, decided.text


def test_list_corrections_scoped_to_owner(
    correction_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    factory, _ = correction_database
    with factory() as db:
        record = db.scalar(select(AttendanceRecord))
        assert record is not None
        record_id = record.id
    use_role(RoleCode.TEACHER, TEACHER_ID)
    created = request_correction(record_id)
    assert created.status_code == 201, created.text

    mine = api_get("/api/v1/attendance/corrections?decision_status=pending")
    assert mine.status_code == 200, mine.text
    assert mine.json()["pagination"]["total"] == 1

    use_role(RoleCode.TEACHER, OTHER_TEACHER_ID)
    # Other teacher owns nothing, so scoped list is empty.
    # Give them TEACHER role but different id; router filters by schedule owner.
    others = api_get("/api/v1/attendance/corrections?decision_status=pending")
    assert others.status_code == 200, others.text
    assert others.json()["pagination"]["total"] == 0

    use_role(RoleCode.ADMIN, ADMIN_ID)
    all_rows = api_get("/api/v1/attendance/corrections")
    assert all_rows.status_code == 200, all_rows.text
    assert all_rows.json()["pagination"]["total"] == 1
