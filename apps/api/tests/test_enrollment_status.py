from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from presensi_api.api.security.dependencies import get_current_user
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
from presensi_api.db.base import Base
from presensi_api.db.models import ClassStudent, FaceTemplate, SchoolClass, Student
from presensi_api.db.session import get_db_session
from presensi_api.main import app


@pytest.fixture
def enrollment_database() -> Generator[sessionmaker[Session], None, None]:
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
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=UUID(int=42),
        email="laborant@example.test",
        full_name="Test Laborant",
        roles=frozenset({RoleCode.LABORANT}),
    )
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


def request(path: str) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get(path)

    return asyncio.run(send())


def test_class_roster_returns_enrollment_status_without_face_payload(
    enrollment_database: sessionmaker[Session],
) -> None:
    with enrollment_database.begin() as session:
        school_class = SchoolClass(
            code="X-A",
            name="Kelas X A",
            grade=10,
            academic_year="2026-2027",
        )
        not_enrolled = Student(student_number="S-001", full_name="Synthetic One")
        enrolled = Student(student_number="S-002", full_name="Synthetic Two")
        needs_reenrollment = Student(
            student_number="S-003", full_name="Synthetic Three"
        )
        session.add_all([school_class, not_enrolled, enrolled, needs_reenrollment])
        session.flush()
        session.add_all(
            [
                ClassStudent(class_id=school_class.id, student_id=student.id)
                for student in (not_enrolled, enrolled, needs_reenrollment)
            ]
        )
        session.add_all(
            [
                FaceTemplate(
                    student_id=enrolled.id,
                    model_name="synthetic-model",
                    model_version="1",
                    quality_metadata={"capture_count": 4},
                ),
                FaceTemplate(
                    student_id=needs_reenrollment.id,
                    model_name="synthetic-model",
                    model_version="1",
                    quality_metadata={"capture_count": 4},
                    revoked_at=datetime.now(UTC),
                ),
            ]
        )
        class_id = school_class.id

    response = request(f"/api/v1/enrollments/class-status?class_id={class_id}")

    assert response.status_code == 200
    assert [
        (row["student_number"], row["template_status"]) for row in response.json()
    ] == [
        ("S-001", "not_enrolled"),
        ("S-002", "enrolled"),
        ("S-003", "needs_reenrollment"),
    ]
    assert "embedding" not in response.text


def test_class_enrollment_status_returns_not_found_for_unknown_class(
    enrollment_database: sessionmaker[Session],
) -> None:
    response = request(f"/api/v1/enrollments/class-status?class_id={UUID(int=77)}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "class_not_found"
