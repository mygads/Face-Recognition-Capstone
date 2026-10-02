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
from presensi_api.auth.bootstrap_admin import (
    BOOTSTRAP_EMAIL,
    bootstrap_development_admin,
)
from presensi_api.db.base import Base
from presensi_api.db.models import AuditLog, AuthSession, Role, User, UserRole
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
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", secrets.token_hex(32))
    monkeypatch.setenv("JWT_ACCESS_TOKEN_TTL_MINUTES", "15")
    monkeypatch.setenv("JWT_SESSION_TTL_HOURS", "24")
    monkeypatch.delenv("JWT_SESSION_COOKIE_SECURE", raising=False)
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
    cookies: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            request_headers = dict(headers or {})
            if token:
                request_headers["Authorization"] = f"Bearer {token}"
            for cookie_name, cookie_value in (cookies or {}).items():
                client.cookies.set(cookie_name, cookie_value)
            return await client.request(
                method,
                path,
                json=body,
                data=form,
                headers=request_headers,
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
        headers={"X-Presensi-Session": "browser"},
    )

    assert response.status_code == 200
    token_data = response.json()
    assert token_data["token_type"] == "bearer"
    assert token_data["expires_in_seconds"] == 900
    assert token_data["password_change_required"] is False
    assert "refresh_token" not in token_data
    assert "session_token" not in token_data
    session_cookie = response.cookies.get("presensi_session")
    assert session_cookie
    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Path=/api/v1/auth" in set_cookie
    assert "Secure" not in set_cookie
    browser_claims = jwt.decode(
        session_cookie,
        os.environ["JWT_SECRET"],
        algorithms=["HS256"],
        issuer="presensi-core-api",
    )
    assert browser_claims["token_use"] == "browser_session"
    assert browser_claims["exp"] - browser_claims["iat"] == 24 * 60 * 60
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
        "must_change_password": False,
    }
    with api_database() as session:
        events = session.scalars(select(AuditLog)).all()
    assert [event.action for event in events] == ["auth.login.succeeded"]
    assert events[0].actor_user_id == user.id
    assert events[0].after_state == {"method": "password", "result": "success"}
    assert password not in str(events[0].after_state)
    assert token_data["access_token"] not in str(events[0].after_state)
    with api_database() as session:
        auth_session = session.get(AuthSession, UUID(browser_claims["jti"]))
    assert auth_session is not None
    assert auth_session.user_id == user.id


def test_bearer_login_without_browser_header_does_not_issue_a_cookie_session(
    api_database: sessionmaker[Session],
) -> None:
    password = secrets.token_urlsafe(24)
    user = add_user(api_database, password)
    response = request(
        "POST",
        "/api/v1/auth/login",
        form={"username": "teacher@example.edu", "password": password},
    )

    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    with api_database() as session:
        browser_sessions = session.scalars(
            select(AuthSession).where(AuthSession.user_id == user.id)
        ).all()
    assert browser_sessions == []


def test_browser_cookie_is_secure_outside_local_development(
    api_database: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    password = secrets.token_urlsafe(24)
    add_user(api_database, password)
    response = request(
        "POST",
        "/api/v1/auth/login",
        form={"username": "teacher@example.edu", "password": password},
        headers={"X-Presensi-Session": "browser"},
    )

    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]


def test_browser_session_refresh_survives_access_token_expiration(
    api_database: sessionmaker[Session],
) -> None:
    password = secrets.token_urlsafe(24)
    user = add_user(api_database, password)
    login_response = request(
        "POST",
        "/api/v1/auth/login",
        form={"username": "teacher@example.edu", "password": password},
        headers={"X-Presensi-Session": "browser"},
    )
    session_cookie = login_response.cookies.get("presensi_session")
    assert session_cookie is not None

    missing_header = request(
        "POST",
        "/api/v1/auth/refresh",
        cookies={"presensi_session": session_cookie},
    )
    assert missing_header.status_code == 403

    refreshed = request(
        "POST",
        "/api/v1/auth/refresh",
        cookies={"presensi_session": session_cookie},
        headers={"X-Presensi-Session": "browser"},
    )
    assert refreshed.status_code == 200
    data = refreshed.json()
    assert data["expires_in_seconds"] == 900
    assert data["access_token"] != login_response.json()["access_token"]
    assert "presensi_session" not in data
    assert (
        request("GET", "/api/v1/auth/me", token=data["access_token"]).status_code == 200
    )

    with api_database() as session:
        auth_session = session.scalar(
            select(AuthSession).where(AuthSession.user_id == user.id)
        )
    assert auth_session is not None
    assert auth_session.last_used_at is not None


def test_logout_revokes_browser_session_and_clears_cookie(
    api_database: sessionmaker[Session],
) -> None:
    password = secrets.token_urlsafe(24)
    user = add_user(api_database, password)
    login_response = request(
        "POST",
        "/api/v1/auth/login",
        form={"username": "teacher@example.edu", "password": password},
        headers={"X-Presensi-Session": "browser"},
    )
    session_cookie = login_response.cookies.get("presensi_session")
    assert session_cookie is not None

    logged_out = request(
        "POST",
        "/api/v1/auth/logout",
        cookies={"presensi_session": session_cookie},
        headers={"X-Presensi-Session": "browser"},
    )
    assert logged_out.status_code == 204
    assert "Max-Age=0" in logged_out.headers["set-cookie"]
    assert (
        request(
            "POST",
            "/api/v1/auth/refresh",
            cookies={"presensi_session": session_cookie},
            headers={"X-Presensi-Session": "browser"},
        ).status_code
        == 401
    )

    with api_database() as session:
        auth_session = session.scalar(
            select(AuthSession).where(AuthSession.user_id == user.id)
        )
        logout_audit = session.scalar(
            select(AuditLog).where(AuditLog.action == "auth.logout.succeeded")
        )
    assert auth_session is not None and auth_session.revoked_at is not None
    assert logout_audit is not None
    assert logout_audit.after_state == {"result": "success"}


def test_browser_session_expiry_is_checked_in_database(
    api_database: sessionmaker[Session],
) -> None:
    password = secrets.token_urlsafe(24)
    user = add_user(api_database, password)
    login_response = request(
        "POST",
        "/api/v1/auth/login",
        form={"username": "teacher@example.edu", "password": password},
        headers={"X-Presensi-Session": "browser"},
    )
    session_cookie = login_response.cookies.get("presensi_session")
    assert session_cookie is not None
    with api_database.begin() as session:
        auth_session = session.scalar(
            select(AuthSession).where(AuthSession.user_id == user.id)
        )
        assert auth_session is not None
        auth_session.created_at = datetime.now(UTC) - timedelta(hours=25)
        auth_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    response = request(
        "POST",
        "/api/v1/auth/refresh",
        cookies={"presensi_session": session_cookie},
        headers={"X-Presensi-Session": "browser"},
    )
    assert response.status_code == 401


def test_development_bootstrap_requires_password_change_before_app_access(
    api_database: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    with api_database.begin() as session:
        seed_roles(session)
        temporary_password = bootstrap_development_admin(session)
        assert temporary_password is not None
        assert bootstrap_development_admin(session) is None

    login_response = request(
        "POST",
        "/api/v1/auth/login",
        form={"username": BOOTSTRAP_EMAIL, "password": temporary_password},
        headers={"X-Presensi-Session": "browser"},
    )
    assert login_response.status_code == 200
    login_data = login_response.json()
    assert login_data["password_change_required"] is True
    restricted_token = login_data["access_token"]
    denied_me = request("GET", "/api/v1/auth/me", token=restricted_token)
    assert denied_me.status_code == 403

    new_password = secrets.token_urlsafe(24)
    change_response = request(
        "POST",
        "/api/v1/auth/change-password",
        body={
            "current_password": temporary_password,
            "new_password": new_password,
        },
        token=restricted_token,
    )
    assert change_response.status_code == 200
    assert change_response.json() == {
        "password_changed": True,
        "sign_in_again": True,
    }
    assert request("GET", "/api/v1/auth/me", token=restricted_token).status_code == 401
    with api_database() as session:
        changed_user = session.scalar(select(User).where(User.email == BOOTSTRAP_EMAIL))
        browser_session = (
            session.scalar(
                select(AuthSession).where(AuthSession.user_id == changed_user.id)
            )
            if changed_user is not None
            else None
        )
    assert browser_session is not None
    assert browser_session.revoked_at is not None

    new_login = request(
        "POST",
        "/api/v1/auth/login",
        form={"username": BOOTSTRAP_EMAIL, "password": new_password},
    )
    assert new_login.status_code == 200
    assert new_login.json()["password_change_required"] is False
    me = request("GET", "/api/v1/auth/me", token=new_login.json()["access_token"])
    assert me.status_code == 200
    assert me.json()["must_change_password"] is False

    with api_database() as session:
        account = session.scalar(select(User).where(User.email == BOOTSTRAP_EMAIL))
        events = session.scalars(select(AuditLog)).all()
    assert account is not None
    assert account.must_change_password is False
    assert account.auth_token_version == 1
    assert all(
        temporary_password not in str(event.after_state)
        and new_password not in str(event.after_state)
        for event in events
    )
    assert "auth.password_changed" in [event.action for event in events]


def test_bootstrap_refuses_non_development_environment(
    api_database: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    with api_database.begin() as session:
        with pytest.raises(RuntimeError, match="only in development"):
            bootstrap_development_admin(session)


def test_development_bootstrap_skips_database_with_existing_accounts(
    api_database: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    with api_database.begin() as session:
        seed_roles(session)
        user = User(
            email="existing-admin@example.edu",
            full_name="Existing administrator",
            password_hash="already-hashed",
        )
        session.add(user)
        session.flush()
        admin_role = session.scalar(select(Role).where(Role.code == "ADMIN"))
        assert admin_role is not None
        session.add(UserRole(user_id=user.id, role_id=admin_role.id))
        session.flush()

        assert bootstrap_development_admin(session) is None
        assert (
            session.scalar(select(User.id).where(User.email == BOOTSTRAP_EMAIL)) is None
        )
        assert len(session.scalars(select(User.id)).all()) == 1


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
        ("TEACHER", "GET", "/api/v1/students", None, 403),
        ("LABORANT", "GET", "/api/v1/students", None, 403),
        ("TEACHER", "GET", f"/api/v1/students/{UUID(int=45)}", None, 403),
        ("LABORANT", "GET", f"/api/v1/students/{UUID(int=45)}", None, 403),
        ("TEACHER", "GET", f"/api/v1/classes/{UUID(int=44)}", None, 403),
        ("LABORANT", "GET", f"/api/v1/classes/{UUID(int=44)}", None, 403),
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
        ("ADMIN", "GET", "/api/v1/face-templates", None, 200),
        ("TEACHER", "GET", "/api/v1/face-templates", None, 403),
        ("LABORANT", "GET", "/api/v1/face-templates", None, 200),
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
            422,
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
            422,
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
            404,
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
            404,
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
