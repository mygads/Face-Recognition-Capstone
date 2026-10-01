from __future__ import annotations

import base64
import json
from collections.abc import Generator
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import ClassVar
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import presensi_api.api.v1.routers.sessions as sessions_router
import presensi_api.attendance_decision as attendance_decision
import presensi_api.session_lifecycle as session_lifecycle
from presensi_api.api.security.dependencies import get_current_user
from presensi_api.api.security.request_rate_limit import SlidingWindowRateLimiter
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
from presensi_api.db.base import Base
from presensi_api.db.models import (
    AttendanceCorrection,
    AttendanceRecord,
    AuditLog,
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
from presensi_api.enrollment_processing import (
    EnrollmentFrameResult,
    get_enrollment_processor,
)
from presensi_api.main import app

SYNTHETIC_DAY = date(2026, 9, 15)
SYNTHETIC_START = datetime(2026, 9, 15, 3, 0, tzinfo=UTC)
ADMIN_ID = UUID("00000000-0000-0000-0000-000000000101")
LABORANT_ID = UUID("00000000-0000-0000-0000-000000000102")
TEACHER_ID = UUID("00000000-0000-0000-0000-000000000103")
OUTSIDE_STUDENT_ID = UUID("00000000-0000-0000-0000-000000000104")
OTHER_TEACHER_ID = UUID("00000000-0000-0000-0000-000000000109")
CLASS_ID = UUID("00000000-0000-0000-0000-000000000105")
LAB_ID = UUID("00000000-0000-0000-0000-000000000106")
SCHEDULE_ID = UUID("00000000-0000-0000-0000-000000000107")
DEVICE_ID = UUID("00000000-0000-0000-0000-000000000108")


class SyntheticEnrollmentProcessor:
    """Fake image processor: marker bytes choose one of two unit embeddings."""

    def process(
        self, image_bytes: bytes, *, model_version: str
    ) -> EnrollmentFrameResult:
        del model_version
        identity_marker = image_bytes[0] // 10
        embedding = (1.0, 0.0, 0.0) if identity_marker == 0 else (0.0, 1.0, 0.0)
        return EnrollmentFrameResult(
            accepted=True,
            model_name="synthetic-enrollment-model",
            model_version="synthetic-v1",
            embedding=embedding,
            quality_score=0.9,
            quality_metadata={"score": 0.9, "accepted": True, "synthetic": True},
        )


class RegressionHarness:
    def __init__(
        self,
        client: TestClient,
        factory: sessionmaker[Session],
        actor: dict[str, AuthenticatedUser],
        clock: dict[str, datetime],
    ) -> None:
        self.client = client
        self.factory = factory
        self.actor = actor
        self.clock = clock
        self.ids: dict[str, UUID] = {
            "admin": ADMIN_ID,
            "laborant": LABORANT_ID,
            "teacher": TEACHER_ID,
            "outside_student": OUTSIDE_STUDENT_ID,
            "class": CLASS_ID,
            "laboratory": LAB_ID,
            "schedule": SCHEDULE_ID,
            "device": DEVICE_ID,
        }

    def use_role(self, role: RoleCode) -> None:
        self.actor["current"] = {
            RoleCode.ADMIN: AuthenticatedUser(
                id=ADMIN_ID,
                email="admin@example.test",
                full_name="Synthetic Admin",
                roles=frozenset({RoleCode.ADMIN}),
            ),
            RoleCode.LABORANT: AuthenticatedUser(
                id=LABORANT_ID,
                email="laborant@example.test",
                full_name="Synthetic Laborant",
                roles=frozenset({RoleCode.LABORANT}),
            ),
            RoleCode.TEACHER: AuthenticatedUser(
                id=TEACHER_ID,
                email="teacher@example.test",
                full_name="Synthetic Teacher",
                roles=frozenset({RoleCode.TEACHER}),
            ),
        }[role]


def _aware_clock(clock: dict[str, datetime]) -> type[datetime]:
    class RegressionClock(datetime):
        frozen: ClassVar[dict[str, datetime]] = clock

        @classmethod
        def now(cls, tz: tzinfo | None = None) -> RegressionClock:
            current = cls.frozen["now"]
            if tz is None:
                current = current.replace(tzinfo=None)
            else:
                current = current.astimezone(tz)
            return cls.fromtimestamp(current.timestamp(), current.tzinfo)

    return RegressionClock


def _principal_for_test(actor: dict[str, AuthenticatedUser]) -> AuthenticatedUser:
    return actor["current"]


def _csv_upload(content: bytes) -> dict[str, tuple[str, bytes, str]]:
    return {"upload": ("synthetic-students.csv", content, "text/csv")}


CaptureUpload = tuple[str, tuple[str, bytes, str]]


def _enrollment_captures(identity_marker: int) -> list[CaptureUpload]:
    return [
        (
            "captures",
            (
                f"synthetic-{identity_marker}-{index}.jpg",
                bytes([identity_marker * 10 + index]) + b"-synthetic-frame-marker",
                "image/jpeg",
            ),
        )
        for index in range(5)
    ]


def _recognition_payload(
    *,
    student_id: UUID,
    device_id: UUID,
    session_id: UUID,
    occurred_at: datetime,
    event_id: UUID | None = None,
) -> dict[str, object]:
    """Return a mocked match decision; this test never invokes a camera/model."""
    return {
        "event_id": str(event_id or uuid4()),
        "device_id": str(device_id),
        "session_id": str(session_id),
        "student_id": str(student_id),
        "outcome": "matched",
        "similarity": "0.990000",
        "confidence": "0.990000",
        "liveness_passed": True,
        "liveness_score": "0.990000",
        "occurred_at": occurred_at.isoformat(),
        "model_name": "synthetic-mock-recognizer",
        "model_version": "synthetic-v1",
    }


def _student_id(factory: sessionmaker[Session], student_number: str) -> UUID:
    with factory() as session:
        student = session.scalar(
            select(Student).where(Student.student_number == student_number)
        )
        assert student is not None
        return UUID(str(student.id))


def _capture_session_roster(
    factory: sessionmaker[Session], session_id: UUID
) -> list[SessionStudent]:
    with factory() as session:
        return list(
            session.scalars(
                select(SessionStudent).where(SessionStudent.session_id == session_id)
            ).all()
        )


def _event_count(factory: sessionmaker[Session], event_id: UUID) -> int:
    from presensi_api.db.models import RecognitionEvent

    with factory() as session:
        return len(
            session.scalars(
                select(RecognitionEvent).where(RecognitionEvent.event_uuid == event_id)
            ).all()
        )


def _attendance_count(factory: sessionmaker[Session], session_id: UUID) -> int:
    with factory() as session:
        return len(
            session.scalars(
                select(AttendanceRecord).where(
                    AttendanceRecord.session_id == session_id
                )
            ).all()
        )


def _one_attendance_for_student(
    factory: sessionmaker[Session], session_id: UUID, student_id: UUID
) -> AttendanceRecord:
    with factory() as session:
        record = session.scalar(
            select(AttendanceRecord).where(
                AttendanceRecord.session_id == session_id,
                AttendanceRecord.student_id == student_id,
            )
        )
        assert record is not None
        return record


def _template_audit_count(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        return len(
            session.scalars(
                select(AuditLog).where(AuditLog.action == "face_template.enrolled")
            ).all()
        )


def _active_template_count(factory: sessionmaker[Session], student_id: UUID) -> int:
    with factory() as session:
        return len(
            session.scalars(
                select(FaceTemplate).where(
                    FaceTemplate.student_id == student_id,
                    FaceTemplate.revoked_at.is_(None),
                )
            ).all()
        )


@pytest.fixture
def regression_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[RegressionHarness, None, None]:
    monkeypatch.setenv(
        "PRESENSI_FACE_TEMPLATE_KEYS",
        json.dumps({"regression-v1": base64.b64encode(b"r" * 32).decode("ascii")}),
    )
    monkeypatch.setenv("PRESENSI_FACE_TEMPLATE_ACTIVE_KEY_ID", "regression-v1")
    monkeypatch.setenv("PRESENSI_ENROLLMENT_DUPLICATE_WARNING_THRESHOLD", "0.92")

    clock = {"now": SYNTHETIC_START}
    regression_clock = _aware_clock(clock)
    monkeypatch.setattr(sessions_router, "datetime", regression_clock)
    monkeypatch.setattr(attendance_decision, "datetime", regression_clock)
    monkeypatch.setattr(session_lifecycle, "datetime", regression_clock)

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

    actor: dict[str, AuthenticatedUser] = {}
    harness = RegressionHarness(TestClient(app), factory, actor, clock)
    harness.use_role(RoleCode.ADMIN)
    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user] = lambda: _principal_for_test(actor)
    processor = SyntheticEnrollmentProcessor()
    app.dependency_overrides[get_enrollment_processor] = lambda: processor
    app.state.request_rate_limiter = SlidingWindowRateLimiter()

    with factory.begin() as session:
        session.add_all(
            [
                User(
                    id=ADMIN_ID,
                    email="admin@example.test",
                    full_name="Synthetic Admin",
                    password_hash="synthetic-test-hash",
                ),
                User(
                    id=LABORANT_ID,
                    email="laborant@example.test",
                    full_name="Synthetic Laborant",
                    password_hash="synthetic-test-hash",
                ),
                User(
                    id=TEACHER_ID,
                    email="teacher@example.test",
                    full_name="Synthetic Teacher",
                    password_hash="synthetic-test-hash",
                ),
                User(
                    id=OTHER_TEACHER_ID,
                    email="other-teacher@example.test",
                    full_name="Other Synthetic Teacher",
                    password_hash="synthetic-test-hash",
                ),
                SchoolClass(
                    id=CLASS_ID,
                    code="X-REG",
                    name="Synthetic Regression Class",
                    grade=10,
                    academic_year="2026-2027",
                ),
                Laboratory(id=LAB_ID, code="LAB-REG", name="Synthetic Lab"),
                Student(
                    id=OUTSIDE_STUDENT_ID,
                    student_number="OUT-001",
                    full_name="Synthetic Outside Roster Student",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                PracticumSchedule(
                    id=SCHEDULE_ID,
                    class_id=CLASS_ID,
                    laboratory_id=LAB_ID,
                    teacher_user_id=TEACHER_ID,
                    subject="Synthetic Practicum",
                    weekday=SYNTHETIC_START.astimezone(
                        ZoneInfo("Asia/Jakarta")
                    ).weekday(),
                    start_time=time(0, 0),
                    end_time=time(23, 59, 59),
                    timezone_name="Asia/Jakarta",
                    effective_from=SYNTHETIC_DAY,
                    effective_through=SYNTHETIC_DAY,
                ),
                Device(
                    id=DEVICE_ID,
                    laboratory_id=LAB_ID,
                    name="Synthetic Recognition Device",
                    device_type="edge_pc",
                ),
            ]
        )

    try:
        yield harness
    finally:
        app.dependency_overrides.clear()
        harness.client.close()
        engine.dispose()


def test_synthetic_school_day_attendance_regression(
    regression_harness: RegressionHarness,
) -> None:
    harness = regression_harness
    client = harness.client

    # 1. ADMIN previews and atomically imports a synthetic class roster.
    harness.use_role(RoleCode.ADMIN)
    csv_bytes = (
        "NIS,Nama,Kelas\n"
        "REG-001,Synthetic Present Student,X-REG\n"
        "REG-002,Synthetic Late Student,X-REG\n"
    ).encode("utf-8")
    mapping = {
        "student_number_column": "NIS",
        "full_name_column": "Nama",
        "class_code_column": "Kelas",
    }
    preview = client.post(
        "/api/v1/students/import/preview",
        data=mapping,
        files=_csv_upload(csv_bytes),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["valid_rows"] == 2
    committed = client.post(
        "/api/v1/students/import/commit",
        data=mapping,
        files=_csv_upload(csv_bytes),
    )
    assert committed.status_code == 201, committed.text
    assert committed.json()["imported_count"] == 2
    present_student_id = _student_id(harness.factory, "REG-001")
    late_student_id = _student_id(harness.factory, "REG-002")

    # 2. LABORANT enrolls two dummy students through a fake, deterministic processor.
    harness.use_role(RoleCode.LABORANT)
    for marker, student_id in ((0, present_student_id), (1, late_student_id)):
        enrollment = client.post(
            "/api/v1/enrollments/captures",
            data={"student_id": str(student_id)},
            files=_enrollment_captures(marker),
        )
        assert enrollment.status_code == 201, enrollment.text
        body = enrollment.json()
        assert body["template_status"] == "enrolled"
        assert body["template_count"] == 5
        assert body["confirmation_required"] is True
        assert "embedding" not in body and "embedding_ciphertext" not in body
        assert _active_template_count(harness.factory, student_id) == 5
    assert _template_audit_count(harness.factory) == 2

    # 3. TEACHER opens an active session; opening snapshots the imported roster.
    harness.use_role(RoleCode.TEACHER)
    opened = client.post(
        "/api/v1/sessions",
        json={
            "practicum_schedule_id": str(harness.ids["schedule"]),
            "grace_period_minutes": 15,
        },
    )
    assert opened.status_code == 201, opened.text
    session_id = UUID(opened.json()["id"])
    opened_at = datetime.fromisoformat(opened.json()["opened_at"])
    roster = _capture_session_roster(harness.factory, session_id)
    assert {entry.student_id for entry in roster} == {
        present_student_id,
        late_student_id,
    }
    assert opened.json()["student_count"] == 2

    # Let the synthetic server clock advance so both fixture capture times are in
    # the past while remaining inside the same active recurring schedule.
    harness.clock["now"] = opened_at + timedelta(minutes=20)

    # 4. A fake valid model match inside the grace period records PRESENT.
    present_event = _recognition_payload(
        student_id=present_student_id,
        device_id=harness.ids["device"],
        session_id=session_id,
        occurred_at=opened_at + timedelta(minutes=5),
    )
    present = client.post("/api/v1/attendance/recognition-events", json=present_event)
    assert present.status_code == 200, present.text
    assert present.json()["decision"] == "attendance_recorded"
    assert present.json()["attendance"]["status"] == "present"

    # 5. A second fake match after the 15-minute grace period records LATE.
    late_event = _recognition_payload(
        student_id=late_student_id,
        device_id=harness.ids["device"],
        session_id=session_id,
        occurred_at=opened_at + timedelta(minutes=16),
    )
    late = client.post("/api/v1/attendance/recognition-events", json=late_event)
    assert late.status_code == 200, late.text
    assert late.json()["attendance"]["status"] == "late"

    # 6. A known student outside the snapshotted roster is recorded as rejected.
    outside_event = _recognition_payload(
        student_id=harness.ids["outside_student"],
        device_id=harness.ids["device"],
        session_id=session_id,
        occurred_at=opened_at + timedelta(minutes=17),
    )
    outside = client.post("/api/v1/attendance/recognition-events", json=outside_event)
    assert outside.status_code == 200, outside.text
    assert outside.json()["decision"] == "no_attendance"
    assert outside.json()["reason"] == "student_not_in_session_roster"
    assert outside.json()["attendance"] is None

    # 7. Retrying the same event UUID returns the original decision without a
    # second event or final attendance row.
    present_event_id = UUID(str(present_event["event_id"]))
    present_retry = client.post(
        "/api/v1/attendance/recognition-events", json=present_event
    )
    assert present_retry.status_code == 200, present_retry.text
    assert present_retry.json()["replayed"] is True
    assert (
        present_retry.json()["attendance"]["id"] == present.json()["attendance"]["id"]
    )
    assert _event_count(harness.factory, present_event_id) == 1
    assert _attendance_count(harness.factory, session_id) == 2

    # 8. Teacher requests a correction; it remains pending and writes an audit row.
    present_record = _one_attendance_for_student(
        harness.factory, session_id, present_student_id
    )
    correction = client.post(
        "/api/v1/attendance/corrections",
        json={
            "attendance_record_id": str(present_record.id),
            "corrected_status": "late",
            "reason": "Synthetic teacher correction regression case",
        },
    )
    assert correction.status_code == 201, correction.text
    correction_id = UUID(correction.json()["id"])
    assert correction.json()["decision_status"] == "pending"
    with harness.factory() as session:
        saved_correction = session.get(AttendanceCorrection, correction_id)
        audit = session.scalar(
            select(AuditLog).where(
                AuditLog.action == "attendance.correction.requested",
                AuditLog.entity_id == correction_id,
            )
        )
        assert saved_correction is not None
        assert saved_correction.decision_status == "pending"
        assert audit is not None and audit.actor_user_id == TEACHER_ID

    with harness.factory.begin() as session:
        schedule = session.get(PracticumSchedule, harness.ids["schedule"])
        assert schedule is not None
        schedule.teacher_user_id = OTHER_TEACHER_ID
    late_record = _one_attendance_for_student(
        harness.factory, session_id, late_student_id
    )
    unauthorized_correction = client.post(
        "/api/v1/attendance/corrections",
        json={
            "attendance_record_id": str(late_record.id),
            "corrected_status": "present",
            "reason": "Synthetic out-of-scope request",
        },
    )
    assert unauthorized_correction.status_code == 404
    with harness.factory.begin() as session:
        schedule = session.get(PracticumSchedule, harness.ids["schedule"])
        assert schedule is not None
        schedule.teacher_user_id = TEACHER_ID

    # 9. Once closed, a new matched event cannot create a final record.
    harness.clock["now"] = opened_at + timedelta(minutes=30)
    closed = client.post(f"/api/v1/sessions/{session_id}/close")
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"
    after_close_event = _recognition_payload(
        student_id=present_student_id,
        device_id=harness.ids["device"],
        session_id=session_id,
        occurred_at=opened_at + timedelta(minutes=31),
    )
    rejected_after_close = client.post(
        "/api/v1/attendance/recognition-events", json=after_close_event
    )
    assert rejected_after_close.status_code == 200, rejected_after_close.text
    assert rejected_after_close.json()["decision"] == "no_attendance"
    assert rejected_after_close.json()["reason"] == "session_inactive"
    assert _attendance_count(harness.factory, session_id) == 2

    # 10. Teacher can export the closed session report as CSV.
    exported = client.get(
        "/api/v1/reports/attendance/export",
        params={
            "starts_on": SYNTHETIC_DAY.isoformat(),
            "ends_on": SYNTHETIC_DAY.isoformat(),
            "format": "csv",
        },
    )
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("text/csv")
    assert "attachment;" in exported.headers["content-disposition"]
    assert "REG-001" in exported.text and "REG-002" in exported.text
