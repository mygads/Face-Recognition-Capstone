from __future__ import annotations

from collections.abc import Generator
from datetime import date, datetime, time, timezone
from uuid import uuid4

import pytest
from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from presensi_api.db.base import Base
from presensi_api.db.models import (
    AttendanceRecord,
    AttendanceSession,
    Device,
    FaceTemplate,
    Laboratory,
    PracticumSchedule,
    RecognitionEvent,
    SchoolClass,
    SessionStudent,
    Student,
    User,
)
from presensi_api.db.seed_roles import ROLE_SEEDS, seed_roles


@pytest.fixture
def database() -> Generator[Engine, None, None]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def attendance_context(database: Engine) -> dict[str, object]:
    with Session(database) as session, session.begin():
        user = User(
            email="teacher@example.test",
            full_name="Test Teacher",
            password_hash="test-hash",
        )
        student = Student(student_number="S-001", full_name="Test Student")
        school_class = SchoolClass(
            code="X-A", name="Class X-A", grade=10, academic_year="2026-2027"
        )
        laboratory = Laboratory(code="LAB-1", name="Laboratory 1")
        session.add_all([user, student, school_class, laboratory])
        session.flush()

        schedule = PracticumSchedule(
            class_id=school_class.id,
            laboratory_id=laboratory.id,
            teacher_user_id=user.id,
            subject="Chemistry",
            weekday=0,
            start_time=time(9, 0),
            end_time=time(10, 0),
            timezone_name="Asia/Jakarta",
            effective_from=date(2026, 1, 1),
        )
        session.add(schedule)
        session.flush()
        attendance_session = AttendanceSession(
            practicum_schedule_id=schedule.id,
            opened_by_user_id=user.id,
            status="active",
        )
        device = Device(
            laboratory_id=laboratory.id, name="Edge PC 1", device_type="edge_pc"
        )
        session.add_all([attendance_session, device])
        session.flush()
        session.add(
            SessionStudent(
                session_id=attendance_session.id,
                student_id=student.id,
                student_number_snapshot=student.student_number,
                full_name_snapshot=student.full_name,
            )
        )
        session.flush()
        ids: dict[str, object] = {
            "student_id": student.id,
            "session_id": attendance_session.id,
            "device_id": device.id,
        }
    return ids


def test_attendance_is_unique_per_student_and_session(
    database: Engine, attendance_context: dict[str, object]
) -> None:
    with Session(database) as session:
        attendance = AttendanceRecord(
            session_id=attendance_context["session_id"],
            student_id=attendance_context["student_id"],
            status="present",
            source="manual",
        )
        session.add(attendance)
        session.commit()

        duplicate = AttendanceRecord(
            session_id=attendance_context["session_id"],
            student_id=attendance_context["student_id"],
            status="late",
            source="manual",
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.commit()


def test_attendance_rejects_students_outside_session_roster(
    database: Engine, attendance_context: dict[str, object]
) -> None:
    with Session(database) as session:
        outsider = Student(student_number="S-OUT", full_name="Outside Roster")
        session.add(outsider)
        session.flush()
        attendance = AttendanceRecord(
            session_id=attendance_context["session_id"],
            student_id=outsider.id,
            status="present",
            source="manual",
        )
        session.add(attendance)
        with pytest.raises(IntegrityError):
            session.commit()


def test_recognition_event_uuid_is_an_idempotency_key(
    database: Engine, attendance_context: dict[str, object]
) -> None:
    event_uuid = uuid4()
    values = {
        "event_uuid": event_uuid,
        "session_id": attendance_context["session_id"],
        "device_id": attendance_context["device_id"],
        "recognized_student_id": attendance_context["student_id"],
        "occurred_at": datetime.now(timezone.utc),
        "outcome": "matched",
        "model_name": "recognition-model",
        "model_version": "1.0.0",
    }
    with Session(database) as session:
        session.add(RecognitionEvent(**values))
        session.commit()
        session.add(RecognitionEvent(**values))
        with pytest.raises(IntegrityError):
            session.commit()


def test_only_one_active_face_template_per_student_and_model_version(
    database: Engine, attendance_context: dict[str, object]
) -> None:
    values = {
        "student_id": attendance_context["student_id"],
        "model_name": "recognition-model",
        "model_version": "1.0.0",
        "quality_metadata": {"quality_score": 0.93},
    }
    with Session(database) as session:
        session.add(FaceTemplate(**values))
        session.commit()

        session.add(FaceTemplate(**values))
        with pytest.raises(IntegrityError):
            session.commit()

        session.rollback()
        session.add(FaceTemplate(**values, revoked_at=datetime.now(timezone.utc)))
        session.commit()


def test_recognition_event_rejects_confidence_outside_unit_interval(
    database: Engine, attendance_context: dict[str, object]
) -> None:
    invalid_event = RecognitionEvent(
        event_uuid=uuid4(),
        session_id=attendance_context["session_id"],
        device_id=attendance_context["device_id"],
        occurred_at=datetime.now(timezone.utc),
        outcome="no_match",
        model_name="recognition-model",
        model_version="1.0.0",
        confidence=1.1,
    )
    with Session(database) as session:
        session.add(invalid_event)
        with pytest.raises(IntegrityError):
            session.commit()


def test_recognition_event_similarity_uses_cosine_range(
    database: Engine, attendance_context: dict[str, object]
) -> None:
    with Session(database) as session:
        session.add(
            RecognitionEvent(
                event_uuid=uuid4(),
                session_id=attendance_context["session_id"],
                device_id=attendance_context["device_id"],
                occurred_at=datetime.now(timezone.utc),
                outcome="no_match",
                model_name="recognition-model",
                model_version="1.0.0",
                similarity=-1.0,
            )
        )
        session.commit()

        session.add(
            RecognitionEvent(
                event_uuid=uuid4(),
                session_id=attendance_context["session_id"],
                device_id=attendance_context["device_id"],
                occurred_at=datetime.now(timezone.utc),
                outcome="no_match",
                model_name="recognition-model",
                model_version="1.0.0",
                similarity=1.01,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_role_seed_is_repeatable(database: Engine) -> None:
    with Session(database) as session:
        assert seed_roles(session) == len(ROLE_SEEDS)
        session.commit()
        assert seed_roles(session) == 0
        session.commit()


def test_face_template_has_metadata_not_face_payload_columns() -> None:
    columns = Base.metadata.tables["face_templates"].columns
    assert {
        "model_name",
        "model_version",
        "quality_metadata",
        "created_at",
        "revoked_at",
    } <= set(columns.keys())
    assert not {"image", "image_blob", "embedding", "face_blob"} & set(columns.keys())


def test_all_datetime_columns_are_timezone_aware() -> None:
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, DateTime):
                assert column.type.timezone is True, f"{table.name}.{column.name}"


def test_student_identifier_is_unique_without_case_sensitivity(
    database: Engine,
) -> None:
    with Session(database) as session:
        session.add(Student(student_number="nis-001", full_name="First Student"))
        session.commit()

    with pytest.raises(IntegrityError):
        with Session(database) as session:
            session.add(Student(student_number="NIS-001", full_name="Second Student"))
            session.commit()
