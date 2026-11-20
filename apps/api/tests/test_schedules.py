from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from presensi_api.api.security.dependencies import get_current_user
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
from presensi_api.db.base import Base
from presensi_api.db.models import PracticumSchedule, Role, User, UserRole
from presensi_api.db.seed_roles import seed_roles
from presensi_api.db.session import get_db_session
from presensi_api.main import app


@pytest.fixture
def api_database() -> Generator[sessionmaker[Session], None, None]:
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
    admin = AuthenticatedUser(
        id=UUID(int=42),
        email="admin@example.test",
        full_name="Test Admin",
        roles=frozenset({RoleCode.ADMIN}),
    )
    app.dependency_overrides[get_current_user] = lambda: admin
    with factory.begin() as session:
        seed_roles(session)
        teacher_role = session.scalar(select(Role).where(Role.code == "TEACHER"))
        assert teacher_role is not None
        teacher = User(
            id=UUID(int=43),
            email="teacher@example.test",
            full_name="Test Teacher",
            password_hash="unused-test-hash",
        )
        other_teacher = User(
            id=UUID(int=44),
            email="teacher2@example.test",
            full_name="Second Teacher",
            password_hash="unused-test-hash",
        )
        session.add_all([teacher, other_teacher])
        session.flush()
        session.add_all(
            [
                UserRole(user_id=teacher.id, role_id=teacher_role.id),
                UserRole(user_id=other_teacher.id, role_id=teacher_role.id),
            ]
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


def setup_master_data() -> tuple[
    dict[str, str], dict[str, str], dict[str, dict[str, str]]
]:
    class_a = request(
        "POST",
        "/api/v1/classes",
        {
            "code": "X-A",
            "name": "Kelas X A",
            "grade": 10,
            "academic_year": "2026-2027",
        },
    ).json()
    class_b = request(
        "POST",
        "/api/v1/classes",
        {
            "code": "X-B",
            "name": "Kelas X B",
            "grade": 10,
            "academic_year": "2026-2027",
        },
    ).json()
    lab_a = request(
        "POST", "/api/v1/laboratories", {"code": "LAB-A", "name": "Lab A"}
    ).json()
    lab_b = request(
        "POST", "/api/v1/laboratories", {"code": "LAB-B", "name": "Lab B"}
    ).json()
    return class_a, class_b, {"a": lab_a, "b": lab_b}


def payload(
    class_id: str,
    laboratory_id: str,
    teacher_id: str,
    *,
    start_time: str = "09:00",
    end_time: str = "10:00",
    effective_from: str = "2026-09-01",
    effective_through: str | None = "2026-09-30",
    weekday: int = 1,
) -> dict[str, object]:
    result: dict[str, object] = {
        "class_id": class_id,
        "laboratory_id": laboratory_id,
        "teacher_user_id": teacher_id,
        "subject": "Praktikum Sintetis",
        "weekday": weekday,
        "start_time": start_time,
        "end_time": end_time,
        "timezone_name": "Asia/Jakarta",
        "effective_from": effective_from,
    }
    if effective_through is not None:
        result["effective_through"] = effective_through
    return result


def upcoming_weekday(day: int, start: date | None = None) -> date:
    reference = start or datetime.now(ZoneInfo("Asia/Jakarta")).date()
    return reference + timedelta(days=(day - reference.weekday()) % 7)


def test_schedule_conflict_detection_and_filters(
    api_database: sessionmaker[Session],
) -> None:
    class_a, class_b, labs = setup_master_data()
    teacher_a = str(UUID(int=43))
    teacher_b = str(UUID(int=44))

    created = request(
        "POST",
        "/api/v1/schedules",
        payload(class_a["id"], labs["a"]["id"], teacher_a),
    )
    assert created.status_code == 201
    assert created.json()["class_name"] == "Kelas X A"
    assert created.json()["laboratory_name"] == "Lab A"
    schedule_id = created.json()["id"]

    # A room overlap conflicts even when class and teacher differ.
    room_conflict = request(
        "POST",
        "/api/v1/schedules",
        payload(
            class_b["id"],
            labs["a"]["id"],
            teacher_b,
            start_time="09:30",
            end_time="10:30",
        ),
    )
    assert room_conflict.status_code == 409
    assert room_conflict.json()["error"]["code"] == "schedule_conflict"

    teacher_conflict = request(
        "POST",
        "/api/v1/schedules",
        payload(
            class_b["id"],
            labs["b"]["id"],
            teacher_a,
            start_time="09:30",
            end_time="10:30",
        ),
    )
    assert teacher_conflict.status_code == 409
    class_conflict = request(
        "POST",
        "/api/v1/schedules",
        payload(
            class_a["id"],
            labs["b"]["id"],
            teacher_b,
            start_time="09:30",
            end_time="10:30",
        ),
    )
    assert class_conflict.status_code == 409

    deactivated = request(
        "PATCH", f"/api/v1/schedules/{schedule_id}", {"is_active": False}
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    replacement = request(
        "POST",
        "/api/v1/schedules",
        payload(class_a["id"], labs["a"]["id"], teacher_a),
    )
    assert replacement.status_code == 201

    # An adjacent slot is allowed, and so is the same slot after the old date window.
    adjacent = request(
        "POST",
        "/api/v1/schedules",
        payload(
            class_a["id"],
            labs["a"]["id"],
            teacher_a,
            start_time="10:00",
            end_time="11:00",
        ),
    )
    assert adjacent.status_code == 201
    later = request(
        "POST",
        "/api/v1/schedules",
        payload(
            class_a["id"],
            labs["a"]["id"],
            teacher_a,
            effective_from="2026-10-01",
            effective_through="2026-10-31",
        ),
    )
    assert later.status_code == 201

    updated = request(
        "PATCH",
        f"/api/v1/schedules/{schedule_id}",
        {"subject": "Praktikum Biologi"},
    )
    assert updated.status_code == 200
    listed = request("GET", "/api/v1/schedules?search=biologi&weekday=1")
    assert listed.status_code == 200
    assert listed.json()["pagination"]["total"] == 1


def test_schedule_validates_references_time_and_teacher_scope(
    api_database: sessionmaker[Session],
) -> None:
    class_a, _, labs = setup_master_data()
    good = payload(class_a["id"], labs["a"]["id"], str(UUID(int=43)))

    unknown_zone = {**good, "timezone_name": "Mars/Olympus"}
    assert request("POST", "/api/v1/schedules", unknown_zone).status_code == 422
    reversed_time = {**good, "start_time": "11:00", "end_time": "10:00"}
    assert request("POST", "/api/v1/schedules", reversed_time).status_code == 422

    teacher_principal = AuthenticatedUser(
        id=UUID(int=43),
        email="teacher@example.test",
        full_name="Test Teacher",
        roles=frozenset({RoleCode.TEACHER}),
    )
    app.dependency_overrides[get_current_user] = lambda: teacher_principal
    self_schedule = request("POST", "/api/v1/schedules", good)
    assert self_schedule.status_code == 201
    own_list = request("GET", "/api/v1/schedules")
    assert own_list.json()["pagination"]["total"] == 1
    other_assignment = request(
        "POST",
        "/api/v1/schedules",
        payload(class_a["id"], labs["a"]["id"], str(UUID(int=44))),
    )
    assert other_assignment.status_code == 403


def test_duplicate_schedule_creates_numbered_one_meeting_per_week_and_splits_source(
    api_database: sessionmaker[Session],
) -> None:
    class_a, _, labs = setup_master_data()
    teacher_id = str(UUID(int=43))
    today = datetime.now(ZoneInfo("Asia/Jakarta")).date()
    first_duplicate_date = upcoming_weekday(1, today) + timedelta(days=7)
    source = request(
        "POST",
        "/api/v1/schedules",
        payload(
            class_a["id"],
            labs["a"]["id"],
            teacher_id,
            effective_from=(today - timedelta(days=28)).isoformat(),
            effective_through=None,
        ),
    )
    assert source.status_code == 201, source.text

    duplicated = request(
        "POST",
        f"/api/v1/schedules/{source.json()['id']}/duplicates",
        {
            "start_date": first_duplicate_date.isoformat(),
            "additional_weeks": 3,
        },
    )
    assert duplicated.status_code == 201, duplicated.text
    result = duplicated.json()
    assert (
        result["source"]["effective_through"]
        == (first_duplicate_date - timedelta(days=1)).isoformat()
    )
    assert [item["subject"] for item in result["duplicates"]] == [
        "Pertemuan 2 - Praktikum Sintetis",
        "Pertemuan 3 - Praktikum Sintetis",
        "Pertemuan 4 - Praktikum Sintetis",
    ]
    assert [item["effective_from"] for item in result["duplicates"]] == [
        first_duplicate_date.isoformat(),
        (first_duplicate_date + timedelta(days=7)).isoformat(),
        (first_duplicate_date + timedelta(days=14)).isoformat(),
    ]
    assert all(
        item["effective_from"] == item["effective_through"]
        and item["weekday"] == result["source"]["weekday"]
        and item["start_time"] == result["source"]["start_time"]
        and item["end_time"] == result["source"]["end_time"]
        for item in result["duplicates"]
    )


def test_duplicate_schedule_until_date_is_inclusive_and_conflicts_are_atomic(
    api_database: sessionmaker[Session],
) -> None:
    class_a, _, labs = setup_master_data()
    teacher_id = str(UUID(int=43))
    today = datetime.now(ZoneInfo("Asia/Jakarta")).date()
    source_start = today - timedelta(days=28)
    source_end = today - timedelta(days=1)
    first_duplicate_date = upcoming_weekday(1, today)
    source = request(
        "POST",
        "/api/v1/schedules",
        payload(
            class_a["id"],
            labs["a"]["id"],
            teacher_id,
            effective_from=source_start.isoformat(),
            effective_through=source_end.isoformat(),
        ),
    )
    assert source.status_code == 201, source.text
    conflict_date = first_duplicate_date + timedelta(days=7)
    conflicting = request(
        "POST",
        "/api/v1/schedules",
        payload(
            class_a["id"],
            labs["a"]["id"],
            teacher_id,
            effective_from=conflict_date.isoformat(),
            effective_through=conflict_date.isoformat(),
        ),
    )
    assert conflicting.status_code == 201, conflicting.text

    duplicated = request(
        "POST",
        f"/api/v1/schedules/{source.json()['id']}/duplicates",
        {
            "start_date": first_duplicate_date.isoformat(),
            "through_date": (first_duplicate_date + timedelta(days=14)).isoformat(),
        },
    )
    assert duplicated.status_code == 409, duplicated.text
    assert duplicated.json()["error"]["code"] == "schedule_conflict"
    assert conflict_date.isoformat() in duplicated.json()["error"]["message"]
    with api_database() as session:
        schedules = session.scalars(select(PracticumSchedule)).all()
        assert len(schedules) == 2
        stored_source = session.get(PracticumSchedule, UUID(source.json()["id"]))
        assert stored_source is not None
        assert stored_source.effective_through == source_end


def test_schedule_update_rejects_conflict_and_can_deactivate(
    api_database: sessionmaker[Session],
) -> None:
    class_a, class_b, labs = setup_master_data()
    teacher_a = str(UUID(int=43))
    first = request(
        "POST",
        "/api/v1/schedules",
        payload(class_a["id"], labs["a"]["id"], teacher_a),
    ).json()
    second = request(
        "POST",
        "/api/v1/schedules",
        payload(
            class_b["id"],
            labs["b"]["id"],
            str(UUID(int=44)),
            start_time="11:00",
            end_time="12:00",
        ),
    ).json()

    conflict = request(
        "PATCH",
        f"/api/v1/schedules/{second['id']}",
        {"start_time": "09:30", "end_time": "10:30", "laboratory_id": labs["a"]["id"]},
    )
    assert conflict.status_code == 409
    deactivated = request(
        "PATCH", f"/api/v1/schedules/{first['id']}", {"is_active": False}
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False


def test_list_schedules_pagination_stable_on_identical_weekday_start(
    api_database: sessionmaker[Session],
) -> None:
    """Same weekday+start_time rows must page without duplication or loss."""
    class_a, class_b, labs = setup_master_data()
    teacher_a = str(UUID(int=43))
    teacher_b = str(UUID(int=44))
    first = request(
        "POST",
        "/api/v1/schedules",
        payload(class_a["id"], labs["a"]["id"], teacher_a),
    )
    assert first.status_code == 201, first.text
    second = request(
        "POST",
        "/api/v1/schedules",
        {
            **payload(class_b["id"], labs["b"]["id"], teacher_b),
            "subject": "Praktikum Kedua",
        },
    )
    assert second.status_code == 201, second.text
    page_one = request("GET", "/api/v1/schedules?limit=1&offset=0")
    page_two = request("GET", "/api/v1/schedules?limit=1&offset=1")
    assert page_one.status_code == 200
    assert page_two.status_code == 200
    first_id = page_one.json()["items"][0]["id"]
    second_id = page_two.json()["items"][0]["id"]
    assert first_id != second_id
    assert {first_id, second_id} == {first.json()["id"], second.json()["id"]}
