from __future__ import annotations

import asyncio
from collections.abc import Callable, Generator
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
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
from presensi_api.session_lifecycle import as_utc


@pytest.fixture
def attendance_database() -> Generator[
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

    principal = AuthenticatedUser(
        id=UUID(int=701),
        email="teacher@example.test",
        full_name="Synthetic Teacher",
        roles=frozenset({RoleCode.TEACHER}),
    )
    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user] = lambda: principal

    local_now = datetime.now(ZoneInfo("Asia/Jakarta"))
    opened_at = datetime.now(UTC) - timedelta(minutes=30)
    with factory.begin() as db:
        teacher = User(
            id=principal.id,
            email=principal.email,
            full_name=principal.full_name,
            password_hash="unused-test-hash",
        )
        other_teacher = User(
            email="other-teacher@example.test",
            full_name="Another Teacher",
            password_hash="unused-test-hash",
        )
        school_class = SchoolClass(
            code="X-A",
            name="Synthetic Class",
            grade=10,
            academic_year="2026-2027",
        )
        laboratory = Laboratory(code="LAB-A", name="Lab A")
        other_laboratory = Laboratory(code="LAB-B", name="Lab B")
        student = Student(student_number="S-001", full_name="Synthetic Student")
        outside_student = Student(
            student_number="S-002", full_name="Outside Roster Student"
        )
        db.add_all(
            [
                teacher,
                other_teacher,
                school_class,
                laboratory,
                other_laboratory,
                student,
                outside_student,
            ]
        )
        db.flush()
        db.add(ClassStudent(class_id=school_class.id, student_id=student.id))
        schedule = PracticumSchedule(
            class_id=school_class.id,
            laboratory_id=laboratory.id,
            teacher_user_id=teacher.id,
            subject="Synthetic Practicum",
            weekday=local_now.weekday(),
            start_time=time(0, 0),
            end_time=time(23, 59, 59),
            timezone_name="Asia/Jakarta",
            effective_from=local_now.date(),
            effective_through=local_now.date(),
        )
        db.add(schedule)
        db.flush()
        device = Device(
            laboratory_id=laboratory.id,
            name="Synthetic Camera",
            device_type="edge_pc",
        )
        db.add(device)
        db.flush()
        attendance_session = AttendanceSession(
            practicum_schedule_id=schedule.id,
            opened_by_user_id=teacher.id,
            status="active",
            opened_at=opened_at,
            grace_period_minutes=15,
        )
        db.add(attendance_session)
        db.flush()
        db.add(
            SessionStudent(
                session_id=attendance_session.id,
                student_id=student.id,
                student_number_snapshot=student.student_number,
                full_name_snapshot=student.full_name,
            )
        )
        ids = {
            "teacher": teacher.id,
            "other_teacher": other_teacher.id,
            "class": school_class.id,
            "laboratory": laboratory.id,
            "other_laboratory": other_laboratory.id,
            "device": device.id,
            "schedule": schedule.id,
            "session": attendance_session.id,
            "student": student.id,
            "outside_student": outside_student.id,
        }
    yield factory, ids
    app.dependency_overrides.clear()
    engine.dispose()


def post_event(body: dict[str, object]) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.post("/api/v1/attendance/recognition-events", json=body)

    return asyncio.run(send())


def event_body(
    ids: dict[str, UUID],
    *,
    event_id: UUID | None = None,
    student_id: UUID | None = None,
    occurred_at: datetime | None = None,
    outcome: str = "matched",
    liveness_passed: bool | None = True,
) -> dict[str, object]:
    now = datetime.now(UTC)
    body: dict[str, object] = {
        "event_id": str(event_id or uuid4()),
        "device_id": str(ids["device"]),
        "session_id": str(ids["session"]),
        "student_id": str(student_id or ids["student"])
        if outcome == "matched" or student_id is not None
        else None,
        "outcome": outcome,
        "similarity": "0.812345",
        "confidence": "0.987654",
        "margin": "0.123456",
        "liveness_passed": liveness_passed,
        "liveness_score": "0.998765" if liveness_passed is not None else None,
        "occurred_at": (occurred_at or now).isoformat(),
        "model_name": "synthetic-sface",
        "model_version": "test-1",
    }
    if outcome != "matched" and student_id is None:
        body["similarity"] = None
        body["confidence"] = None
        body["margin"] = None
    return body


def test_present_event_persists_evidence_and_final_attendance(
    attendance_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    factory, ids = attendance_database
    with factory() as db:
        attendance_session = db.get(AttendanceSession, ids["session"])
        assert attendance_session is not None
        occurred_at = as_utc(attendance_session.opened_at) + timedelta(minutes=14)

    response = post_event(event_body(ids, occurred_at=occurred_at))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"] == "attendance_recorded"
    assert body["reason"] is None
    assert body["attendance"]["status"] == "present"
    assert body["attendance"]["student_id"] == str(ids["student"])
    with factory() as db:
        recognition = db.scalar(select(RecognitionEvent))
        record = db.scalar(select(AttendanceRecord))
        assert recognition is not None and record is not None
        assert recognition.event_uuid == UUID(body["event_id"])
        assert recognition.similarity == Decimal("0.812345")
        assert recognition.confidence == Decimal("0.987654")
        assert recognition.quality_metadata["liveness_passed"] is True
        attendance_decision = recognition.quality_metadata["attendance_decision"]
        assert isinstance(attendance_decision, dict)
        assert attendance_decision["status"] == "present"
        assert record.recognition_event_id == recognition.id
        assert record.source == "face_recognition"


def test_event_after_grace_period_is_late(
    attendance_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    factory, ids = attendance_database
    with factory() as db:
        attendance_session = db.get(AttendanceSession, ids["session"])
        assert attendance_session is not None
        occurred_at = as_utc(attendance_session.opened_at) + timedelta(minutes=16)

    response = post_event(event_body(ids, occurred_at=occurred_at))

    assert response.status_code == 200
    assert response.json()["attendance"]["status"] == "late"
    with factory() as db:
        record = db.scalar(select(AttendanceRecord))
        assert record is not None and record.status == "late"


@pytest.mark.parametrize(
    ("rejection", "mutate"),
    [
        (
            "device_laboratory_mismatch",
            lambda db, ids: setattr(
                db.get(Device, ids["device"]), "laboratory_id", ids["other_laboratory"]
            ),
        ),
        (
            "session_inactive",
            lambda db, ids: setattr(
                db.get(AttendanceSession, ids["session"]), "status", "closed"
            ),
        ),
        (
            "device_inactive",
            lambda db, ids: setattr(db.get(Device, ids["device"]), "is_active", False),
        ),
    ],
)
def test_invalid_device_or_inactive_session_is_stored_without_attendance(
    attendance_database: tuple[sessionmaker[Session], dict[str, UUID]],
    rejection: str,
    mutate: Callable[[Session, dict[str, UUID]], None],
) -> None:
    factory, ids = attendance_database
    with factory.begin() as db:
        mutate(db, ids)

    response = post_event(event_body(ids))

    assert response.status_code == 200
    assert response.json()["decision"] == "no_attendance"
    assert response.json()["reason"] == rejection
    with factory() as db:
        assert db.scalar(select(RecognitionEvent)) is not None
        assert db.scalar(select(AttendanceRecord)) is None


def test_student_must_be_in_session_roster(
    attendance_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    factory, ids = attendance_database

    response = post_event(event_body(ids, student_id=ids["outside_student"]))

    assert response.status_code == 200
    assert response.json()["reason"] == "student_not_in_session_roster"
    with factory() as db:
        assert db.scalar(select(RecognitionEvent)) is not None
        assert db.scalar(select(AttendanceRecord)) is None


def test_unknown_candidate_is_preserved_as_auditable_rejection(
    attendance_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    factory, ids = attendance_database
    unknown_student = uuid4()

    response = post_event(event_body(ids, student_id=unknown_student))

    assert response.status_code == 200
    assert response.json()["reason"] == "student_not_found"
    with factory() as db:
        recognition = db.scalar(select(RecognitionEvent))
        assert recognition is not None
        assert recognition.recognized_student_id is None
        assert recognition.outcome == "error"
        assert recognition.quality_metadata["reported_student_id"] == str(
            unknown_student
        )
        assert db.scalar(select(AttendanceRecord)) is None


@pytest.mark.parametrize(
    ("outcome", "liveness_passed", "reason"),
    [
        ("ambiguous", True, "recognition_not_matched"),
        ("no_match", None, "recognition_not_matched"),
        ("matched", False, "liveness_failed"),
    ],
)
def test_nonmatch_or_failed_liveness_cannot_finalize_attendance(
    attendance_database: tuple[sessionmaker[Session], dict[str, UUID]],
    outcome: str,
    liveness_passed: bool | None,
    reason: str,
) -> None:
    factory, ids = attendance_database

    response = post_event(
        event_body(ids, outcome=outcome, liveness_passed=liveness_passed)
    )

    assert response.status_code == 200
    assert response.json()["reason"] == reason
    with factory() as db:
        assert db.scalar(select(RecognitionEvent)) is not None
        assert db.scalar(select(AttendanceRecord)) is None


def test_duplicate_student_session_attendance_keeps_second_event_only(
    attendance_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    factory, ids = attendance_database
    first = post_event(event_body(ids))
    second = post_event(event_body(ids))

    assert first.status_code == second.status_code == 200
    assert first.json()["decision"] == "attendance_recorded"
    assert second.json()["reason"] == "attendance_already_recorded"
    with factory() as db:
        assert len(db.scalars(select(RecognitionEvent)).all()) == 2
        assert len(db.scalars(select(AttendanceRecord)).all()) == 1


def test_same_event_id_retry_is_idempotent_and_returns_original_decision(
    attendance_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    factory, ids = attendance_database
    body = event_body(ids, event_id=uuid4())

    first = post_event(body)
    retry = post_event(body)

    assert first.status_code == retry.status_code == 200
    assert first.json()["attendance"] == retry.json()["attendance"]
    assert first.json()["replayed"] is False
    assert retry.json()["replayed"] is True
    with factory() as db:
        assert len(db.scalars(select(RecognitionEvent)).all()) == 1
        assert len(db.scalars(select(AttendanceRecord)).all()) == 1


def test_reusing_event_id_with_different_payload_conflicts(
    attendance_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    factory, ids = attendance_database
    event_id = uuid4()
    original = event_body(ids, event_id=event_id)
    changed = event_body(ids, event_id=event_id)
    changed["similarity"] = "0.812346"

    first = post_event(original)
    conflict = post_event(changed)

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "event_id_reused"
    with factory() as db:
        assert len(db.scalars(select(RecognitionEvent)).all()) == 1
        assert len(db.scalars(select(AttendanceRecord)).all()) == 1


def test_teacher_cannot_submit_another_teachers_session(
    attendance_database: tuple[sessionmaker[Session], dict[str, UUID]],
) -> None:
    factory, ids = attendance_database
    with factory.begin() as db:
        schedule = db.get(PracticumSchedule, ids["schedule"])
        assert schedule is not None
        schedule.teacher_user_id = ids["other_teacher"]

    response = post_event(event_body(ids))

    assert response.status_code == 200
    assert response.json()["reason"] == "session_not_accessible"
    with factory() as db:
        assert db.scalar(select(RecognitionEvent)) is not None
        assert db.scalar(select(AttendanceRecord)) is None
