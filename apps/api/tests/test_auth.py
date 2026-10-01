from __future__ import annotations

import asyncio
import os
import secrets
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import jwt
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from presensi_api.api.security.dependencies import get_current_user
from presensi_api.api.security.passwords import hash_password
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
from presensi_api.db.base import Base
from presensi_api.db.models import AuditLog, Role, User, UserRole
from presensi_api.db.seed_roles import seed_roles
from presensi_api.db.session import get_db_session
from presensi_api.main import app


@pytest.fixture
def api_database(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[sessionmaker[Session], None, None]:
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
    monkeypatch.setenv("JWT_SECRET", secrets.token_hex(32))
    monkeypatch.setenv("JWT_ACCESS_TOKEN_TTL_MINUTES", "15")
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


def request(
    method: str,
    path: str,
    *,
    body: dict[str, object] | None = None,
    form: dict[str, str] | None = None,
    token: str | None = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"Authorization": f"Bearer {token}"} if token else None
            return await client.request(
                method, path, json=body, data=form, headers=headers
            )

    return asyncio.run(send())


def add_user(
    factory: sessionmaker[Session], password: str, role_code: str = "TEACHER"
) -> User:
    with factory.begin() as session:
        seed_roles(session)
        role = session.scalar(select(Role).where(Role.code == role_code))
        assert role is not None
        user = User(
            email="teacher@example.edu",
            full_name="Test Teacher",
            password_hash=hash_password(password),
        )
        session.add(user)
        session.flush()
        session.add(UserRole(user_id=user.id, role_id=role.id))
        session.flush()
        session.expunge(user)
        return user


def test_oauth_login_issues_expiring_access_token_and_me(
    api_database: sessionmaker[Session],
) -> None:
    password = secrets.token_urlsafe(24)
    user = add_user(api_database, password)
    with api_database() as session:
        stored_user = session.get(User, user.id)
    assert stored_user is not None
    assert stored_user.password_hash.startswith("$argon2id$")
    assert stored_user.password_hash != password

    response = request(
        "POST",
        "/api/v1/auth/login",
        form={
            "username": "TEACHER@example.edu",
            "password": password,
        },
    )

    assert response.status_code == 200
    token_data = response.json()
    assert token_data["token_type"] == "bearer"
    assert token_data["expires_in_seconds"] == 900
    assert "refresh_token" not in token_data
    claims = jwt.decode(
        token_data["access_token"],
        os.environ["JWT_SECRET"],
        algorithms=["HS256"],
        issuer="presensi-core-api",
    )
    assert claims["sub"] == str(user.id)
    assert claims["token_use"] == "access"
    assert claims["exp"] - claims["iat"] == 900

    me = request("GET", "/api/v1/auth/me", token=token_data["access_token"])
    assert me.status_code == 200
    assert me.json() == {
        "id": str(user.id),
        "email": "teacher@example.edu",
        "full_name": "Test Teacher",
        "roles": ["TEACHER"],
    }
    with api_database() as session:
        events = session.scalars(select(AuditLog)).all()
    assert [event.action for event in events] == ["auth.login.succeeded"]
    assert events[0].actor_user_id == user.id
    assert events[0].after_state == {"method": "password", "result": "success"}
    assert password not in str(events[0].after_state)
    assert token_data["access_token"] not in str(events[0].after_state)


def test_failed_login_audits_successfully_without_credentials(
    api_database: sessionmaker[Session],
) -> None:
    invalid_password = secrets.token_urlsafe(24)
    unknown_password = secrets.token_urlsafe(24)
    add_user(api_database, secrets.token_urlsafe(24))
    bad_password = request(
        "POST",
        "/api/v1/auth/login",
        form={
            "username": "teacher@example.edu",
            "password": invalid_password,
        },
    )
    unknown_user = request(
        "POST",
        "/api/v1/auth/login",
        form={"username": "unknown@example.edu", "password": unknown_password},
    )

    assert bad_password.status_code == unknown_user.status_code == 401
    assert bad_password.json() == unknown_user.json()
    with api_database() as session:
        events = session.scalars(select(AuditLog).order_by(AuditLog.action)).all()
    assert len(events) == 2
    assert {event.action for event in events} == {"auth.login.failed"}
    for event in events:
        audit_text = str(event.after_state)
        assert set(event.after_state or {}) == {"method", "result"}
        assert invalid_password not in audit_text
        assert unknown_password not in audit_text
        assert "token" not in audit_text
        assert "@" not in audit_text
        assert event.actor_user_id is None


def test_expired_bearer_token_is_rejected(api_database: sessionmaker[Session]) -> None:
    user = add_user(api_database, secrets.token_urlsafe(24))
    now = datetime.now(UTC)
    expired_token = jwt.encode(
        {
            "sub": str(user.id),
            "iat": now - timedelta(minutes=10),
            "exp": now - timedelta(minutes=5),
            "jti": str(UUID(int=2)),
            "iss": "presensi-core-api",
            "token_use": "access",
        },
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )

    response = request("GET", "/api/v1/auth/me", token=expired_token)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(
    ("role", "method", "path", "body", "expected_status"),
    [
        ("ADMIN", "GET", "/api/v1/classes", None, 200),
        ("TEACHER", "GET", "/api/v1/classes", None, 200),
        ("LABORANT", "GET", "/api/v1/classes", None, 200),
        (
            "ADMIN",
            "POST",
            "/api/v1/students",
            {"student_number": "S1", "full_name": "Student"},
            201,
        ),
        (
            "TEACHER",
            "POST",
            "/api/v1/students",
            {"student_number": "S1", "full_name": "Student"},
            403,
        ),
        (
            "LABORANT",
            "POST",
            "/api/v1/students",
            {"student_number": "S1", "full_name": "Student"},
            403,
        ),
        ("ADMIN", "GET", "/api/v1/schedules", None, 200),
        ("TEACHER", "GET", "/api/v1/schedules", None, 200),
        ("LABORANT", "GET", "/api/v1/schedules", None, 403),
        (
            "ADMIN",
            "POST",
            "/api/v1/schedules",
            {
                "class_id": str(UUID(int=7)),
                "laboratory_id": str(UUID(int=8)),
                "teacher_user_id": str(UUID(int=9)),
                "subject": "Practicum",
                "weekday": 1,
                "start_time": "09:00",
                "end_time": "10:00",
                "timezone_name": "Asia/Jakarta",
                "effective_from": "2026-09-01",
            },
            422,
        ),
        (
            "TEACHER",
            "POST",
            "/api/v1/schedules",
            {
                "class_id": str(UUID(int=7)),
                "laboratory_id": str(UUID(int=8)),
                "teacher_user_id": str(UUID(int=9)),
                "subject": "Practicum",
                "weekday": 1,
                "start_time": "09:00",
                "end_time": "10:00",
                "timezone_name": "Asia/Jakarta",
                "effective_from": "2026-09-01",
            },
            422,
        ),
        (
            "LABORANT",
            "POST",
            "/api/v1/schedules",
            {
                "class_id": str(UUID(int=7)),
                "laboratory_id": str(UUID(int=8)),
                "teacher_user_id": str(UUID(int=9)),
                "subject": "Practicum",
                "weekday": 1,
                "start_time": "09:00",
                "end_time": "10:00",
                "timezone_name": "Asia/Jakarta",
                "effective_from": "2026-09-01",
            },
            403,
        ),
        ("ADMIN", "GET", "/api/v1/devices", None, 200),
        ("TEACHER", "GET", "/api/v1/devices", None, 403),
        ("LABORANT", "GET", "/api/v1/devices", None, 200),
        (
            "ADMIN",
            "POST",
            "/api/v1/enrollments",
            {
                "student_id": str(UUID(int=3)),
                "device_id": str(UUID(int=4)),
                "model_name": "model",
                "model_version": "1",
            },
            501,
        ),
        (
            "TEACHER",
            "POST",
            "/api/v1/enrollments",
            {
                "student_id": str(UUID(int=3)),
                "device_id": str(UUID(int=4)),
                "model_name": "model",
                "model_version": "1",
            },
            403,
        ),
        (
            "LABORANT",
            "POST",
            "/api/v1/enrollments",
            {
                "student_id": str(UUID(int=3)),
                "device_id": str(UUID(int=4)),
                "model_name": "model",
                "model_version": "1",
            },
            501,
        ),
        (
            "ADMIN",
            "GET",
            f"/api/v1/enrollments/class-status?class_id={UUID(int=44)}",
            None,
            404,
        ),
        (
            "TEACHER",
            "GET",
            f"/api/v1/enrollments/class-status?class_id={UUID(int=44)}",
            None,
            403,
        ),
        (
            "LABORANT",
            "GET",
            f"/api/v1/enrollments/class-status?class_id={UUID(int=44)}",
            None,
            404,
        ),
        (
            "ADMIN",
            "POST",
            "/api/v1/sessions",
            {"practicum_schedule_id": str(UUID(int=5))},
            404,
        ),
        (
            "TEACHER",
            "POST",
            "/api/v1/sessions",
            {"practicum_schedule_id": str(UUID(int=5))},
            404,
        ),
        (
            "LABORANT",
            "POST",
            "/api/v1/sessions",
            {"practicum_schedule_id": str(UUID(int=5))},
            404,
        ),
        ("ADMIN", "GET", "/api/v1/sessions", None, 200),
        ("TEACHER", "GET", "/api/v1/sessions", None, 200),
        ("LABORANT", "GET", "/api/v1/sessions", None, 200),
        (
            "ADMIN",
            "GET",
            f"/api/v1/sessions/{UUID(int=51)}",
            None,
            404,
        ),
        (
            "TEACHER",
            "GET",
            f"/api/v1/sessions/{UUID(int=51)}",
            None,
            404,
        ),
        (
            "LABORANT",
            "GET",
            f"/api/v1/sessions/{UUID(int=51)}",
            None,
            404,
        ),
        ("ADMIN", "GET", "/api/v1/attendance", None, 501),
        ("TEACHER", "GET", "/api/v1/attendance", None, 501),
        ("LABORANT", "GET", "/api/v1/attendance", None, 501),
        (
            "ADMIN",
            "POST",
            "/api/v1/attendance/corrections",
            {
                "attendance_record_id": str(UUID(int=6)),
                "corrected_status": "present",
                "reason": "Correction",
            },
            501,
        ),
        (
            "TEACHER",
            "POST",
            "/api/v1/attendance/corrections",
            {
                "attendance_record_id": str(UUID(int=6)),
                "corrected_status": "present",
                "reason": "Correction",
            },
            501,
        ),
        (
            "LABORANT",
            "POST",
            "/api/v1/attendance/corrections",
            {
                "attendance_record_id": str(UUID(int=6)),
                "corrected_status": "present",
                "reason": "Correction",
            },
            403,
        ),
        ("ADMIN", "GET", "/api/v1/accounts", None, 501),
        ("TEACHER", "GET", "/api/v1/accounts", None, 403),
        ("LABORANT", "GET", "/api/v1/accounts", None, 403),
        (
            "ADMIN",
            "GET",
            "/api/v1/reports/attendance?starts_on=2026-09-01&ends_on=2026-09-30",
            None,
            200,
        ),
        (
            "TEACHER",
            "GET",
            "/api/v1/reports/attendance?starts_on=2026-09-01&ends_on=2026-09-30",
            None,
            200,
        ),
        (
            "LABORANT",
            "GET",
            "/api/v1/reports/attendance?starts_on=2026-09-01&ends_on=2026-09-30",
            None,
            403,
        ),
    ],
)
def test_endpoint_role_permissions(
    api_database: sessionmaker[Session],
    role: str,
    method: str,
    path: str,
    body: dict[str, object] | None,
    expected_status: int,
) -> None:
    principal = AuthenticatedUser(
        id=UUID(int=1),
        email=f"{role.lower()}@example.edu",
        full_name=role,
        roles=frozenset({RoleCode(role)}),
    )
    app.dependency_overrides[get_current_user] = lambda: principal
    try:
        response = request(method, path, body=body)
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == expected_status
    if expected_status == 403:
        assert response.json()["error"]["code"] == "forbidden"
