from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

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
    Laboratory,
    PracticumSchedule,
    RuntimeConfigurationVersion,
    SchoolClass,
    SessionStudent,
    Student,
    User,
)
from presensi_api.db.session import get_db_session
from presensi_api.main import app
from presensi_api.runtime_configuration import AT_RISK_POLICY_SCOPE

ADMIN_ID = UUID("00000000-0000-0000-0000-000000000001")
TEACHER_A_ID = UUID("00000000-0000-0000-0000-000000000002")
TEACHER_B_ID = UUID("00000000-0000-0000-0000-000000000003")
LABORANT_ID = UUID("00000000-0000-0000-0000-000000000004")
STUDENT_A1_ID = UUID("00000000-0000-0000-0000-000000000011")
STUDENT_A2_ID = UUID("00000000-0000-0000-0000-000000000012")
STUDENT_A3_ID = UUID("00000000-0000-0000-0000-000000000013")
STUDENT_B1_ID = UUID("00000000-0000-0000-0000-000000000014")
CLASS_A_ID = UUID("00000000-0000-0000-0000-000000000021")
CLASS_B_ID = UUID("00000000-0000-0000-0000-000000000022")
LAB_A_ID = UUID("00000000-0000-0000-0000-000000000031")
LAB_B_ID = UUID("00000000-0000-0000-0000-000000000032")
SCHEDULE_A_ID = UUID("00000000-0000-0000-0000-000000000041")
SCHEDULE_B_ID = UUID("00000000-0000-0000-0000-000000000042")


@pytest.fixture
def at_risk_database() -> Generator[dict[str, object], None, None]:
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
    now = datetime.now(UTC).replace(microsecond=0)

    def closed_session(
        db: Session, session_id: UUID, schedule_id: UUID, opened: datetime
    ) -> AttendanceSession:
        item = AttendanceSession(
            id=session_id,
            practicum_schedule_id=schedule_id,
            opened_by_user_id=TEACHER_A_ID,
            status="closed",
            opened_at=opened,
            closed_at=opened + timedelta(hours=1),
            grace_period_minutes=15,
        )
        db.add(item)
        return item

    def roster(
        db: Session, session_id: UUID, student_id: UUID, number: str, name: str
    ) -> None:
        db.add(
            SessionStudent(
                session_id=session_id,
                student_id=student_id,
                student_number_snapshot=number,
                full_name_snapshot=name,
            )
        )

    def mark(
        db: Session,
        session_id: UUID,
        student_id: UUID,
        status: str,
        recorded_at: datetime,
    ) -> None:
        db.add(
            AttendanceRecord(
                session_id=session_id,
                student_id=student_id,
                status=status,
                source="manual",
                recorded_at=recorded_at,
            )
        )

    with factory.begin() as db:
        db.add_all(
            [
                User(
                    id=ADMIN_ID,
                    email="admin@example.test",
                    full_name="Test Admin",
                    password_hash="test-hash",
                ),
                User(
                    id=TEACHER_A_ID,
                    email="teacher-a@example.test",
                    full_name="Teacher A",
                    password_hash="test-hash",
                ),
                User(
                    id=TEACHER_B_ID,
                    email="teacher-b@example.test",
                    full_name="Teacher B",
                    password_hash="test-hash",
                ),
                Student(
                    id=STUDENT_A1_ID, student_number="S-A1", full_name="Siswa A1"
                ),
                Student(
                    id=STUDENT_A2_ID, student_number="S-A2", full_name="Siswa A2"
                ),
                Student(
                    id=STUDENT_A3_ID, student_number="S-A3", full_name="Siswa A3"
                ),
                Student(
                    id=STUDENT_B1_ID, student_number="S-B1", full_name="Siswa B1"
                ),
                SchoolClass(
                    id=CLASS_A_ID,
                    code="X-A",
                    name="Class A",
                    grade=10,
                    academic_year="2026-2027",
                ),
                SchoolClass(
                    id=CLASS_B_ID,
                    code="X-B",
                    name="Class B",
                    grade=10,
                    academic_year="2026-2027",
                ),
                Laboratory(id=LAB_A_ID, code="LAB-A", name="Lab A"),
                Laboratory(id=LAB_B_ID, code="LAB-B", name="Lab B"),
                PracticumSchedule(
                    id=SCHEDULE_A_ID,
                    class_id=CLASS_A_ID,
                    laboratory_id=LAB_A_ID,
                    teacher_user_id=TEACHER_A_ID,
                    subject="Chemistry",
                    weekday=1,
                    start_time=time(9),
                    end_time=time(10),
                    timezone_name="Asia/Jakarta",
                    effective_from=date(2026, 1, 1),
                    is_active=True,
                ),
                PracticumSchedule(
                    id=SCHEDULE_B_ID,
                    class_id=CLASS_B_ID,
                    laboratory_id=LAB_B_ID,
                    teacher_user_id=TEACHER_B_ID,
                    subject="Physics",
                    weekday=2,
                    start_time=time(10),
                    end_time=time(11),
                    timezone_name="Asia/Jakarta",
                    effective_from=date(2026, 1, 1),
                    is_active=True,
                ),
            ]
        )
        a1_open = now - timedelta(days=25)
        a2_open = now - timedelta(days=20)
        a3_open = now - timedelta(days=15)
        for index, opened in enumerate((a1_open, a2_open, a3_open)):
            closed_session(
                db,
                UUID(f"00000000-0000-0000-0000-00000000010{index + 1}"),
                SCHEDULE_A_ID,
                opened,
            )
        a4_open = now - timedelta(days=10)
        closed_session(
            db, UUID("00000000-0000-0000-0000-000000000104"), SCHEDULE_A_ID, a4_open
        )
        db.add(
            AttendanceSession(
                id=UUID("00000000-0000-0000-0000-000000000105"),
                practicum_schedule_id=SCHEDULE_A_ID,
                opened_by_user_id=TEACHER_A_ID,
                status="active",
                opened_at=now - timedelta(days=2),
                grace_period_minutes=15,
            )
        )
        db.add(
            AttendanceSession(
                id=UUID("00000000-0000-0000-0000-000000000106"),
                practicum_schedule_id=SCHEDULE_A_ID,
                opened_by_user_id=TEACHER_A_ID,
                status="cancelled",
                opened_at=now - timedelta(days=12),
                grace_period_minutes=15,
            )
        )
        old_open = now - timedelta(days=40)
        closed_session(
            db, UUID("00000000-0000-0000-0000-000000000107"), SCHEDULE_A_ID, old_open
        )
        closed_session(
            db,
            UUID("00000000-0000-0000-0000-000000000108"),
            SCHEDULE_B_ID,
            now - timedelta(days=9),
        )
        db.flush()
        in_window = [
            UUID("00000000-0000-0000-0000-000000000101"),
            UUID("00000000-0000-0000-0000-000000000102"),
            UUID("00000000-0000-0000-0000-000000000103"),
            UUID("00000000-0000-0000-0000-000000000104"),
            UUID("00000000-0000-0000-0000-000000000105"),
        ]
        for session_id in in_window:
            roster(db, session_id, STUDENT_A1_ID, "S-A1", "Siswa A1")
            roster(db, session_id, STUDENT_A2_ID, "S-A2", "Siswa A2")
            roster(db, session_id, STUDENT_A3_ID, "S-A3", "Siswa A3")
        roster(
            db,
            UUID("00000000-0000-0000-0000-000000000106"),
            STUDENT_A1_ID,
            "S-A1",
            "Siswa A1",
        )
        roster(
            db,
            UUID("00000000-0000-0000-0000-000000000107"),
            STUDENT_A1_ID,
            "S-A1",
            "Siswa A1",
        )
        roster(
            db,
            UUID("00000000-0000-0000-0000-000000000108"),
            STUDENT_B1_ID,
            "S-B1",
            "Siswa B1",
        )
        mark(
            db,
            UUID("00000000-0000-0000-0000-000000000101"),
            STUDENT_A1_ID,
            "absent",
            a1_open + timedelta(minutes=30),
        )
        mark(
            db,
            UUID("00000000-0000-0000-0000-000000000101"),
            STUDENT_A2_ID,
            "present",
            a1_open + timedelta(minutes=5),
        )
        mark(
            db,
            UUID("00000000-0000-0000-0000-000000000101"),
            STUDENT_A3_ID,
            "excused",
            a1_open + timedelta(minutes=5),
        )
        mark(
            db,
            UUID("00000000-0000-0000-0000-000000000102"),
            STUDENT_A1_ID,
            "absent",
            a2_open + timedelta(minutes=30),
        )
        mark(
            db,
            UUID("00000000-0000-0000-0000-000000000102"),
            STUDENT_A2_ID,
            "late",
            a2_open + timedelta(minutes=30),
        )
        mark(
            db,
            UUID("00000000-0000-0000-0000-000000000102"),
            STUDENT_A3_ID,
            "present",
            a2_open + timedelta(minutes=5),
        )
        mark(
            db,
            UUID("00000000-0000-0000-0000-000000000103"),
            STUDENT_A2_ID,
            "late",
            a3_open + timedelta(minutes=30),
        )
        mark(
            db,
            UUID("00000000-0000-0000-0000-000000000103"),
            STUDENT_A3_ID,
            "excused",
            a3_open + timedelta(minutes=5),
        )
        mark(
            db,
            UUID("00000000-0000-0000-0000-000000000104"),
            STUDENT_A1_ID,
            "present",
            a4_open + timedelta(minutes=5),
        )
        mark(
            db,
            UUID("00000000-0000-0000-0000-000000000104"),
            STUDENT_A2_ID,
            "late",
            a4_open + timedelta(minutes=30),
        )
        mark(
            db,
            UUID("00000000-0000-0000-0000-000000000104"),
            STUDENT_A3_ID,
            "present",
            a4_open + timedelta(minutes=5),
        )
        mark(
            db,
            UUID("00000000-0000-0000-0000-000000000107"),
            STUDENT_A1_ID,
            "absent",
            old_open + timedelta(minutes=30),
        )
        mark(
            db,
            UUID("00000000-0000-0000-0000-000000000108"),
            STUDENT_B1_ID,
            "absent",
            now - timedelta(days=9) + timedelta(minutes=30),
        )
    yield {
        "factory": factory,
        "a3_closed_at": a3_open + timedelta(hours=1),
    }
    app.dependency_overrides.clear()
    engine.dispose()


def principal(role: RoleCode, user_id: UUID) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=user_id,
        email=f"{role.value.lower()}@example.test",
        full_name=role.value,
        roles=frozenset({role}),
    )


def request(
    method: str,
    path: str,
    user: AuthenticatedUser | None = None,
    body: dict[str, object] | None = None,
) -> httpx.Response:
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    elif get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]

    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.request(method, path, json=body)

    return asyncio.run(send())


def rows_by_student(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    items = payload["items"]
    assert isinstance(items, list)
    return {item["student_id"]: item for item in items}


def test_absent_rate_flags_student_with_counts(
    at_risk_database: dict[str, object],
) -> None:
    admin = principal(RoleCode.ADMIN, ADMIN_ID)
    response = request("GET", "/api/v1/reports/attendance/at-risk", admin)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["effective_window_days"] == 30
    assert payload["effective_absence_pct_threshold"] == 20.0
    assert payload["effective_late_count_threshold"] == 3
    assert payload["policy_revision"] == 0
    row = rows_by_student(payload)[str(STUDENT_A1_ID)]
    assert row["total_sessions"] == 5
    assert row["absent_count"] == 3
    assert row["late_count"] == 0
    assert row["absence_pct"] == 60.0
    assert row["reasons"] == ["tingkat_absen"]
    assert row["class_name"] == "Class A"
    a3_closed_at = at_risk_database["a3_closed_at"]
    assert isinstance(a3_closed_at, datetime)
    assert row["last_absent_at"] == a3_closed_at.isoformat()


def test_repeated_lateness_flags_student(
    at_risk_database: dict[str, object],
) -> None:
    admin = principal(RoleCode.ADMIN, ADMIN_ID)
    response = request("GET", "/api/v1/reports/attendance/at-risk", admin)
    assert response.status_code == 200, response.text
    row = rows_by_student(response.json())[str(STUDENT_A2_ID)]
    assert row["total_sessions"] == 5
    assert row["absent_count"] == 0
    assert row["late_count"] == 3
    assert row["absence_pct"] == 0.0
    assert row["reasons"] == ["sering_terlambat"]
    assert row["last_absent_at"] is None


def test_excused_records_never_count_as_absent(
    at_risk_database: dict[str, object],
) -> None:
    admin = principal(RoleCode.ADMIN, ADMIN_ID)
    response = request(
        "GET",
        "/api/v1/reports/attendance/at-risk?absence_pct=0&late_count=100",
        admin,
    )
    assert response.status_code == 200, response.text
    row = rows_by_student(response.json())[str(STUDENT_A3_ID)]
    assert row["total_sessions"] == 5
    assert row["absent_count"] == 0
    assert row["late_count"] == 0


def test_cancelled_sessions_excluded_from_totals(
    at_risk_database: dict[str, object],
) -> None:
    admin = principal(RoleCode.ADMIN, ADMIN_ID)
    response = request("GET", "/api/v1/reports/attendance/at-risk", admin)
    assert response.status_code == 200, response.text
    row = rows_by_student(response.json())[str(STUDENT_A1_ID)]
    assert row["total_sessions"] == 5


def test_open_sessions_not_counted_as_absent(
    at_risk_database: dict[str, object],
) -> None:
    admin = principal(RoleCode.ADMIN, ADMIN_ID)
    response = request("GET", "/api/v1/reports/attendance/at-risk", admin)
    assert response.status_code == 200, response.text
    row = rows_by_student(response.json())[str(STUDENT_A1_ID)]
    assert row["absent_count"] == 3


def test_sessions_outside_window_ignored(
    at_risk_database: dict[str, object],
) -> None:
    admin = principal(RoleCode.ADMIN, ADMIN_ID)
    response = request(
        "GET", "/api/v1/reports/attendance/at-risk?window_days=180", admin
    )
    assert response.status_code == 200, response.text
    row = rows_by_student(response.json())[str(STUDENT_A1_ID)]
    assert row["total_sessions"] == 6
    assert row["absent_count"] == 4


def test_teacher_sees_only_owned_schedules(
    at_risk_database: dict[str, object],
) -> None:
    teacher_a = principal(RoleCode.TEACHER, TEACHER_A_ID)
    response = request("GET", "/api/v1/reports/attendance/at-risk", teacher_a)
    assert response.status_code == 200, response.text
    assert set(rows_by_student(response.json())) == {
        str(STUDENT_A1_ID),
        str(STUDENT_A2_ID),
    }
    teacher_b = principal(RoleCode.TEACHER, TEACHER_B_ID)
    response = request("GET", "/api/v1/reports/attendance/at-risk", teacher_b)
    assert response.status_code == 200, response.text
    assert set(rows_by_student(response.json())) == {str(STUDENT_B1_ID)}


def test_admin_and_laborant_see_all_flagged_students(
    at_risk_database: dict[str, object],
) -> None:
    expected = {str(STUDENT_A1_ID), str(STUDENT_A2_ID), str(STUDENT_B1_ID)}
    admin = principal(RoleCode.ADMIN, ADMIN_ID)
    response = request("GET", "/api/v1/reports/attendance/at-risk", admin)
    assert response.status_code == 200, response.text
    assert set(rows_by_student(response.json())) == expected
    laborant = principal(RoleCode.LABORANT, LABORANT_ID)
    response = request("GET", "/api/v1/reports/attendance/at-risk", laborant)
    assert response.status_code == 200, response.text
    assert set(rows_by_student(response.json())) == expected


def test_invalid_window_rejected_with_envelope(
    at_risk_database: dict[str, object],
) -> None:
    admin = principal(RoleCode.ADMIN, ADMIN_ID)
    for query in ("window_days=0", "window_days=181"):
        response = request(
            "GET", f"/api/v1/reports/attendance/at-risk?{query}", admin
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


def test_missing_token_rejected(
    at_risk_database: dict[str, object],
) -> None:
    response = request("GET", "/api/v1/reports/attendance/at-risk", None)
    assert response.status_code == 401
    assert "error" in response.json()


def test_policy_returns_defaults_initially(
    at_risk_database: dict[str, object],
) -> None:
    admin = principal(RoleCode.ADMIN, ADMIN_ID)
    response = request("GET", "/api/v1/reports/attendance/at-risk/policy", admin)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "window_days": 30,
        "absence_pct_threshold": 20.0,
        "late_count_threshold": 3,
        "revision": 0,
        "updated_at": None,
    }


def test_policy_update_requires_manage_settings(
    at_risk_database: dict[str, object],
) -> None:
    teacher = principal(RoleCode.TEACHER, TEACHER_A_ID)
    response = request(
        "PUT",
        "/api/v1/reports/attendance/at-risk/policy",
        teacher,
        {"window_days": 60, "absence_pct_threshold": 50.0, "late_count_threshold": 5},
    )
    assert response.status_code == 403


def test_policy_update_publishes_revision(
    at_risk_database: dict[str, object],
) -> None:
    admin = principal(RoleCode.ADMIN, ADMIN_ID)
    published = request(
        "PUT",
        "/api/v1/reports/attendance/at-risk/policy",
        admin,
        {"window_days": 60, "absence_pct_threshold": 50.0, "late_count_threshold": 5},
    )
    assert published.status_code == 200, published.text
    assert published.json()["revision"] == 1
    assert published.json()["absence_pct_threshold"] == 50.0

    stored = request("GET", "/api/v1/reports/attendance/at-risk/policy", admin)
    assert stored.status_code == 200
    assert stored.json()["window_days"] == 60
    assert stored.json()["revision"] == 1
    assert stored.json()["updated_at"] is not None


def test_policy_update_writes_audit_log(
    at_risk_database: dict[str, object],
) -> None:
    admin = principal(RoleCode.ADMIN, ADMIN_ID)
    published = request(
        "PUT",
        "/api/v1/reports/attendance/at-risk/policy",
        admin,
        {"window_days": 60, "absence_pct_threshold": 50.0, "late_count_threshold": 5},
    )
    assert published.status_code == 200, published.text
    factory = at_risk_database["factory"]
    assert isinstance(factory, sessionmaker)
    with factory() as session:
        audit = session.scalar(
            select(AuditLog).where(
                AuditLog.action == "runtime_configuration.published"
            )
        )
        assert audit is not None
        assert audit.actor_user_id == ADMIN_ID
        assert audit.after_state is not None
        assert audit.after_state["scope_key"] == AT_RISK_POLICY_SCOPE
        assert audit.after_state["revision"] == 1


def test_policy_rejects_out_of_range_values(
    at_risk_database: dict[str, object],
) -> None:
    admin = principal(RoleCode.ADMIN, ADMIN_ID)
    response = request(
        "PUT",
        "/api/v1/reports/attendance/at-risk/policy",
        admin,
        {"window_days": 500, "absence_pct_threshold": 20.0, "late_count_threshold": 3},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_corrupt_stored_policy_falls_back_to_defaults(
    at_risk_database: dict[str, object],
) -> None:
    factory = at_risk_database["factory"]
    assert isinstance(factory, sessionmaker)
    with factory.begin() as session:
        session.add(
            RuntimeConfigurationVersion(
                scope_key=AT_RISK_POLICY_SCOPE,
                revision=1,
                settings={
                    "window_days": "segera",
                    "absence_pct_threshold": -5,
                    "late_count_threshold": 999,
                },
                actor_user_id=ADMIN_ID,
            )
        )
    admin = principal(RoleCode.ADMIN, ADMIN_ID)
    response = request("GET", "/api/v1/reports/attendance/at-risk/policy", admin)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["window_days"] == 30
    assert payload["absence_pct_threshold"] == 20.0
    assert payload["late_count_threshold"] == 3
    assert payload["revision"] == 1


def test_query_thresholds_override_stored_policy(
    at_risk_database: dict[str, object],
) -> None:
    admin = principal(RoleCode.ADMIN, ADMIN_ID)
    published = request(
        "PUT",
        "/api/v1/reports/attendance/at-risk/policy",
        admin,
        {"window_days": 30, "absence_pct_threshold": 90.0, "late_count_threshold": 99},
    )
    assert published.status_code == 200, published.text
    strict = request("GET", "/api/v1/reports/attendance/at-risk", admin)
    assert strict.status_code == 200
    assert str(STUDENT_A1_ID) not in rows_by_student(strict.json())
    relaxed = request(
        "GET", "/api/v1/reports/attendance/at-risk?absence_pct=50", admin
    )
    assert relaxed.status_code == 200, relaxed.text
    payload = relaxed.json()
    assert payload["effective_absence_pct_threshold"] == 50.0
    assert payload["effective_late_count_threshold"] == 99
    assert payload["policy_revision"] == 1
    assert payload["items"][0]["student_id"] == str(STUDENT_A1_ID)
