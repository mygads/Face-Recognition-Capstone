from __future__ import annotations

import asyncio
from collections.abc import Generator
from uuid import UUID

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from presensi_api.api.security.dependencies import get_current_user
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
from presensi_api.db.base import Base
from presensi_api.db.models import Role, User, UserRole
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
    with api_database.begin() as session:
        roles = [
            Role(code=code, name=name)
            for code, name in (
                ("ADMIN", "Admin"),
                ("TEACHER", "Guru"),
                ("LABORANT", "Laboran"),
            )
        ]
        session.add_all(roles)
        session.flush()
        roles_by_code = {role.code: role for role in roles}
        users_by_email = {
            user.email: user for user in session.scalars(select(User)).all()
        }
        session.add_all(
            [
                UserRole(
                    user_id=users_by_email["admin@example.test"].id,
                    role_id=roles_by_code["ADMIN"].id,
                ),
                UserRole(
                    user_id=users_by_email["teacher@example.test"].id,
                    role_id=roles_by_code["TEACHER"].id,
                ),
                UserRole(
                    user_id=users_by_email["laborant@example.test"].id,
                    role_id=roles_by_code["LABORANT"].id,
                ),
            ]
        )

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
            "roles",
            "is_active",
            "created_at",
        }
        assert "password_hash" not in str(item)
    assert payload["items"][0]["roles"] == ["ADMIN"]
    assert payload["items"][1]["roles"] == ["LABORANT"]
    assert second.json()["items"][0]["roles"] == ["TEACHER"]


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


def _user_id(factory: sessionmaker[Session], email: str) -> UUID:
    with factory() as session:
        user = session.query(User).filter(User.email == email).one()
        return user.id


def test_laborant_can_read_own_lab_assignments(
    api_database: sessionmaker[Session],
) -> None:
    laborant_id = _user_id(api_database, "laborant@example.test")
    principal = AuthenticatedUser(
        id=laborant_id,
        email="laborant@example.test",
        full_name="Test Laborant",
        roles=frozenset({RoleCode.LABORANT}),
    )
    response = request(
        "GET",
        f"/api/v1/accounts/{laborant_id}/laborant-assignments",
        principal=principal,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"items": []}


def test_laborant_cannot_read_other_lab_assignments(
    api_database: sessionmaker[Session],
) -> None:
    laborant_id = _user_id(api_database, "laborant@example.test")
    teacher_id = _user_id(api_database, "teacher@example.test")
    principal = AuthenticatedUser(
        id=laborant_id,
        email="laborant@example.test",
        full_name="Test Laborant",
        roles=frozenset({RoleCode.LABORANT}),
    )
    response = request(
        "GET",
        f"/api/v1/accounts/{teacher_id}/laborant-assignments",
        principal=principal,
    )
    assert response.status_code == 403


def test_teacher_can_read_own_class_assignments(
    api_database: sessionmaker[Session],
) -> None:
    teacher_id = _user_id(api_database, "teacher@example.test")
    principal = AuthenticatedUser(
        id=teacher_id,
        email="teacher@example.test",
        full_name="Test Teacher",
        roles=frozenset({RoleCode.TEACHER}),
    )
    response = request(
        "GET",
        f"/api/v1/accounts/{teacher_id}/teacher-assignments",
        principal=principal,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"items": []}


def test_class_laboratories_not_shadowed_by_account_id_route(
    api_database: sessionmaker[Session],
) -> None:
    response = request("GET", "/api/v1/accounts/class-laboratories")
    assert response.status_code == 200, response.text
    assert response.json() == {"items": []}


def test_set_password_updates_hash_and_revokes_sessions(
    api_database: sessionmaker[Session],
) -> None:
    from sqlalchemy import select

    with api_database() as session:
        target = session.scalars(
            select(User).where(User.email == "teacher@example.test")
        ).one()
        target_id = str(target.id)
    response = asyncio.run(_post_set_password(target_id, "BaruKuat123"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["must_change_password"] is False
    with api_database() as session:
        updated = session.get(User, UUID(str(target_id)))
        assert updated is not None
        assert updated.password_hash != "unused-test-hash"
        assert updated.must_change_password is False


async def _post_set_password(account_id: str, password: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.post(
            f"/api/v1/accounts/{account_id}/set-password",
            json={"new_password": password},
        )


def test_set_password_rejects_short_password(
    api_database: sessionmaker[Session],
) -> None:
    from sqlalchemy import select

    with api_database() as session:
        target = session.scalars(
            select(User).where(User.email == "teacher@example.test")
        ).one()
        target_id = str(target.id)
    response = asyncio.run(_post_set_password(target_id, "pendek"))
    assert response.status_code == 422, response.text


def test_set_password_forbids_teacher_principal(
    api_database: sessionmaker[Session],
) -> None:
    from sqlalchemy import select

    teacher = AuthenticatedUser(
        id=UUID(int=44),
        email="teacher@example.test",
        full_name="Test Teacher",
        roles=frozenset({RoleCode.TEACHER}),
    )
    with api_database() as session:
        target = session.scalars(
            select(User).where(User.email == "teacher@example.test")
        ).one()
        target_id = str(target.id)
    app.dependency_overrides[get_current_user] = lambda: teacher

    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.post(
                f"/api/v1/accounts/{target_id}/set-password",
                json={"new_password": "BaruKuat123"},
            )

    response = asyncio.run(send())
    assert response.status_code == 403, response.text
