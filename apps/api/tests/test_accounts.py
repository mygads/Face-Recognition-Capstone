from __future__ import annotations

import asyncio
from collections.abc import Generator
from uuid import UUID

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from presensi_api.api.security.dependencies import get_current_user
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
from presensi_api.db.base import Base
from presensi_api.db.models import User
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
    principal = AuthenticatedUser(
        id=UUID(int=43),
        email="admin@example.test",
        full_name="Test Admin",
        roles=frozenset({RoleCode.ADMIN}),
    )
    app.dependency_overrides[get_current_user] = lambda: principal
    with factory.begin() as session:
        session.add_all(
            [
                User(
                    id=principal.id,
                    email=principal.email,
                    full_name=principal.full_name,
                    password_hash="unused-test-hash",
                ),
                User(
                    email="teacher@example.test",
                    full_name="Test Teacher",
                    password_hash="unused-test-hash",
                ),
                User(
                    email="laborant@example.test",
                    full_name="Test Laborant",
                    password_hash="unused-test-hash",
                ),
            ]
        )
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


def request(
    method: str,
    path: str,
    *,
    query: str = "",
    principal: AuthenticatedUser | None = None,
    authenticated: bool = True,
) -> httpx.Response:
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: (
            principal
            if principal is not None
            else AuthenticatedUser(
                id=UUID(int=43),
                email="admin@example.test",
                full_name="Test Admin",
                roles=frozenset({RoleCode.ADMIN}),
            )
        )
    elif get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]

    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.request(method, path + query)

    return asyncio.run(send())


def test_list_accounts_returns_email_order_and_pagination(
    api_database: sessionmaker[Session],
) -> None:
    response = request("GET", "/api/v1/accounts", query="?limit=2&offset=0")
    assert response.status_code == 200
    payload = response.json()
    assert payload["pagination"] == {"total": 3, "limit": 2, "offset": 0}
    assert [item["email"] for item in payload["items"]] == [
        "admin@example.test",
        "laborant@example.test",
    ]

    second = request("GET", "/api/v1/accounts", query="?limit=2&offset=2")
    assert second.status_code == 200
    assert [item["email"] for item in second.json()["items"]] == [
        "teacher@example.test"
    ]
    for item in payload["items"]:
        assert set(item) == {
            "id",
            "email",
            "full_name",
            "is_active",
            "created_at",
        }
        assert "password_hash" not in str(item)


def test_list_accounts_forbids_teacher_principal(
    api_database: sessionmaker[Session],
) -> None:
    teacher = AuthenticatedUser(
        id=UUID(int=44),
        email="teacher@example.test",
        full_name="Test Teacher",
        roles=frozenset({RoleCode.TEACHER}),
    )
    response = request("GET", "/api/v1/accounts", principal=teacher)
    assert response.status_code == 403


def test_list_accounts_requires_authentication(
    api_database: sessionmaker[Session],
) -> None:
    response = request("GET", "/api/v1/accounts", authenticated=False)
    assert response.status_code == 401
