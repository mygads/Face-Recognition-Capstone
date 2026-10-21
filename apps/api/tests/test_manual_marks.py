from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime, time
from uuid import UUID, uuid4
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
    Device,
    Laboratory,
    PracticumSchedule,
    RecognitionEvent,
    SchoolClass,
    SessionStudent,
    Student,
    User,
)
from presensi_api.db.session import get_db_session
from presensi_api.main import app

TEACHER_ID = UUID(int=901)
OTHER_TEACHER_ID = UUID(int=902)


@pytest.fixture
def manual_marks_database() -> Generator[
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
        other_teacher = User(
            id=OTHER_TEACHER_ID,
            email="other@example.test",
            full_name="Other Teacher",
            password_hash="unused-test-hash",
        )
        school_class = SchoolClass(
            code="X-M",
            name="Synthetic Class",
            grade=10,
            academic_year="2026-2027",
        )
        laboratory = Laboratory(code="LAB-M", name="Lab M")
        first = Student(student_number="S-001", full_name="Siswa Satu")
        second = Student(student_number="S-002", full_name="Siswa Dua")
        outsider = Student(student_number="S-003", full_name="Outside Roster")
        db.add_all(
            [teacher, other_teacher, school_class, laboratory, first, second, outsider]
        )
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
        other_schedule = PracticumSchedule(
            class_id=school_class.id,
            laboratory_id=laboratory.id,
            teacher_user_id=other_teacher.id,
            subject="Other Practicum",
            weekday=local_now.weekday(),
            start_time=time(0, 0),
            end_time=time(23, 59),
            timezone_name="Asia/Jakarta",
            effective_from=local_now.date(),
            effective_through=local_now.date(),
        )
        db.add_all([schedule, other_schedule])
        db.flush()
        db.add_all(
            [
                ClassStudent(class_id=school_class.id, student_id=first.id),
                ClassStudent(class_id=school_class.id, student_id=second.id),
            ]
        )
        opened_at = datetime.now(UTC)
        own_session = AttendanceSession(
            practicum_schedule_id=schedule.id,
            opened_by_user_id=teacher.id,
            status="manual_override",
            opened_at=opened_at,
            grace_period_minutes=15,
        )
        other_session = AttendanceSession(
            practicum_schedule_id=other_schedule.id,
            opened_by_user_id=other_teacher.id,
            status="active",
            opened_at=opened_at,
            grace_period_minutes=15,
        )
        db.add_all([own_session, other_session])
        db.flush()
        for attendance_session in (own_session, other_session):
            for student in (first, second):
                db.add(
                    SessionStudent(
                        session_id=attendance_session.id,
                        student_id=student.id,
                        student_number_snapshot=student.student_number,
                        full_name_snapshot=student.full_name,
                        snapshot_taken_at=opened_at,
                    )
                )
        ids = {
            "teacher": teacher.id,
            "schedule": schedule.id,
            "session": own_session.id,
            "other_session": other_session.id,
            "first": first.id,
            "second": second.id,
            "outsider": outsider.id,
        }
    yield factory, ids
    app.dependency_overrides.clear()
    engine.dispose()


def post_mark(session_id: UUID, body: dict[str, object] | None) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.post(
                f"/api/v1/attendance/sessions/{session_id}/manual-marks",
                json=body,
            )

    return asyncio.run(send())


@pytest.mark.parametrize("attendance_status", ["present", "late", "absent", "excused"])
def test_manual_mark_records_each_status_without_overwrite(
    manual_marks_database: tuple[sessionmaker[Session], dict[str, UUID]],
    attendance_status: str,
) -> None:
    factory, ids = manual_marks_database
    response = post_mark(
        ids["session"],
        {"student_id": str(ids["first"]), "status": attendance_status},
    )
    assert response.status_code == 201, response.text
    record = response.json()["record"]
    assert record["session_id"] == str(ids["session"])
    assert record["student_id"] == str(ids["first"])
    assert record["status"] == attendance_status
    assert record["source"] == "manual"
    assert record["recognition_event_id"] is None

    with factory() as db:
        stored = db.scalar(select(AttendanceRecord))
        assert stored is not None
        assert stored.recorded_by_user_id == TEACHER_ID
        assert stored.source == "manual"
        audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "attendance.manual_marked")
        )
        assert audit is not None
        assert audit.actor_user_id == TEACHER_ID
        assert audit.after_state is not None
        assert audit.after_state["status"] == attendance_status
        assert audit.after_state["source"] == "manual"


def test_manual_mark_note_is_trimmed_and_blank_becomes_none(
    manual_marks_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    factory, ids = manual_marks_database
    response = post_mark(
        ids["session"],
        {
            "student_id": str(ids["first"]),
            "status": "excused",
            "note": "  Surat dokter  ",
        },
    )
    assert response.status_code == 201, response.text
    blank = post_mark(
        ids["session"],
        {"student_id": str(ids["second"]), "status": "absent", "note": "   "},
    )
    assert blank.status_code == 201, blank.text

    with factory() as db:
        audits = db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "attendance.manual_marked")
            .order_by(AuditLog.created_at)
        ).all()
        notes = []
        for audit in audits:
            assert audit.after_state is not None
            notes.append(audit.after_state["note"])
        assert notes == [
            "Surat dokter",
            None,
        ]


def test_manual_mark_rejects_long_note(
    manual_marks_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    _, ids = manual_marks_database
    response = post_mark(
        ids["session"],
        {"student_id": str(ids["first"]), "status": "present", "note": "x" * 501},
    )
    assert response.status_code == 422


def test_manual_mark_is_teacher_scoped(
    manual_marks_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    _, ids = manual_marks_database
    response = post_mark(
        ids["other_session"],
        {"student_id": str(ids["first"]), "status": "present"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"

    roster = asyncio.run(_get(f"/api/v1/sessions/{ids['other_session']}/roster"))
    assert roster.status_code == 404


async def _get(path: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.get(path)


def test_manual_mark_unknown_and_outside_roster_students(
    manual_marks_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    _, ids = manual_marks_database
    unknown = post_mark(
        ids["session"], {"student_id": str(uuid4()), "status": "present"}
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "student_not_found"

    outside = post_mark(
        ids["session"], {"student_id": str(ids["outsider"]), "status": "present"}
    )
    assert outside.status_code == 404
    assert outside.json()["error"]["code"] == "student_not_in_session_roster"


def test_manual_mark_duplicate_conflicts_including_face_recognition_record(
    manual_marks_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    factory, ids = manual_marks_database
    first = post_mark(
        ids["session"], {"student_id": str(ids["first"]), "status": "present"}
    )
    assert first.status_code == 201
    duplicate = post_mark(
        ids["session"], {"student_id": str(ids["first"]), "status": "late"}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "attendance_already_recorded"

    with factory.begin() as db:
        laboratory = db.scalars(select(Laboratory)).one()
        device = Device(
            laboratory_id=laboratory.id,
            name="Synthetic Edge",
            device_type="edge_pc",
        )
        db.add(device)
        db.flush()
        event = RecognitionEvent(
            event_uuid=uuid4(),
            session_id=ids["session"],
            device_id=device.id,
            recognized_student_id=ids["second"],
            occurred_at=datetime.now(UTC),
            outcome="matched",
            model_name="synthetic",
            model_version="v1",
        )
        db.add(event)
        db.flush()
        db.add(
            AttendanceRecord(
                session_id=ids["session"],
                student_id=ids["second"],
                recognition_event_id=event.id,
                recorded_by_user_id=None,
                status="present",
                source="face_recognition",
                recorded_at=datetime.now(UTC),
            )
        )
    over_recognition = post_mark(
        ids["session"], {"student_id": str(ids["second"]), "status": "late"}
    )
    assert over_recognition.status_code == 409
    assert over_recognition.json()["error"]["code"] == "attendance_already_recorded"


def test_manual_mark_on_inactive_session_conflicts(
    manual_marks_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    factory, ids = manual_marks_database
    with factory.begin() as db:
        attendance_session = db.get(AttendanceSession, ids["session"])
        assert attendance_session is not None
        attendance_session.status = "closed"
    closed = post_mark(
        ids["session"], {"student_id": str(ids["first"]), "status": "present"}
    )
    assert closed.status_code == 409
    assert closed.json()["error"]["code"] == "session_inactive"

    with factory.begin() as db:
        attendance_session = db.get(AttendanceSession, ids["session"])
        assert attendance_session is not None
        attendance_session.status = "cancelled"
    cancelled = post_mark(
        ids["session"], {"student_id": str(ids["first"]), "status": "present"}
    )
    assert cancelled.status_code == 409
    assert cancelled.json()["error"]["code"] == "session_inactive"


def test_manual_mark_requires_session_operator_permission(
    manual_marks_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    _, ids = manual_marks_database
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=uuid4(),
        email="nobody@example.test",
        full_name="No Roles",
        roles=frozenset(),
    )
    try:
        forbidden = post_mark(
            ids["session"], {"student_id": str(ids["first"]), "status": "present"}
        )
    finally:
        app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            id=TEACHER_ID,
            email="teacher@example.test",
            full_name="Synthetic Teacher",
            roles=frozenset({RoleCode.TEACHER}),
        )
    assert forbidden.status_code == 403


def test_manual_mark_rejects_unknown_session(
    manual_marks_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    _, ids = manual_marks_database
    response = post_mark(
        uuid4(), {"student_id": str(ids["first"]), "status": "present"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"


def test_session_roster_reports_record_status(
    manual_marks_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    _, ids = manual_marks_database
    before = asyncio.run(_get(f"/api/v1/sessions/{ids['session']}/roster"))
    assert before.status_code == 200
    assert {row["student_id"]: row["record_status"] for row in before.json()} == {
        str(ids["first"]): None,
        str(ids["second"]): None,
    }

    marked = post_mark(
        ids["session"], {"student_id": str(ids["first"]), "status": "late"}
    )
    assert marked.status_code == 201

    after = asyncio.run(_get(f"/api/v1/sessions/{ids['session']}/roster"))
    assert after.status_code == 200
    assert {row["student_id"]: row["record_status"] for row in after.json()} == {
        str(ids["first"]): "late",
        str(ids["second"]): None,
    }


def test_manual_mark_never_accepts_image_or_embedding_fields(
    manual_marks_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    _, ids = manual_marks_database
    response = post_mark(
        ids["session"],
        {
            "student_id": str(ids["first"]),
            "status": "present",
            "image_base64": "aGVsbG8=",
            "embedding": [0.1, 0.2],
        },
    )
    assert response.status_code == 422
