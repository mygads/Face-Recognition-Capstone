from __future__ import annotations

import asyncio
from collections.abc import Generator
from uuid import UUID

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from presensi_api.api.security.dependencies import get_current_user
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
from presensi_api.db.base import Base
from presensi_api.db.session import get_db_session
from presensi_api.main import app


def send_request(
    method: str, path: str, body: dict[str, object] | None = None
) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.request(method, path, json=body)

    return asyncio.run(send())


def test_versioned_health_endpoint() -> None:
    response = send_request("GET", "/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_legacy_process_health_alias_remains_available() -> None:
    response = send_request("GET", "/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_lists_each_versioned_router_group() -> None:
    document = app.openapi()

    assert {
        "/api/v1/health",
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/accounts",
        "/api/v1/students",
        "/api/v1/classes",
        "/api/v1/laboratories",
        "/api/v1/devices",
        "/api/v1/devices/{device_id}/active-sessions",
        "/api/v1/devices/{device_id}/active-session-cache",
        "/api/v1/devices/{device_id}/credentials",
        "/api/v1/schedules",
        "/api/v1/sessions",
        "/api/v1/sessions/{session_id}/dashboard",
        "/api/v1/enrollments",
        "/api/v1/enrollments/class-status",
        "/api/v1/enrollments/captures",
        "/api/v1/face-templates",
        "/api/v1/attendance",
        "/api/v1/attendance/recognition-events",
        "/api/v1/attendance/corrections",
        "/api/v1/reports/attendance",
    } <= set(document["paths"])
    assert "/health" not in document["paths"]


def test_openapi_uses_pydantic_contract_and_shared_error_schema() -> None:
    document = app.openapi()
    student_create = document["paths"]["/api/v1/students"]["post"]
    schemas = document["components"]["schemas"]

    assert "StudentCreateRequest" in schemas
    assert "StudentResponse" in schemas
    assert "ErrorEnvelope" in schemas
    assert "EnrollmentStudentStatusResponse" in schemas
    assert "EnrollmentCaptureResultResponse" in schemas
    assert "RecognitionEventRequest" in schemas
    assert "RecognitionEventDecisionResponse" in schemas
    assert "SessionDashboardSnapshot" in schemas
    assert "SessionRecentActivity" in schemas
    dashboard_fields = set(schemas["SessionDashboardSnapshot"]["properties"])
    assert {"summary", "devices", "recent_activity"} <= dashboard_fields
    dashboard_properties = str(schemas["SessionDashboardSnapshot"]["properties"])
    assert not {"embedding", "image", "photo", "blob"} & {
        name
        for name in ("embedding", "image", "photo", "blob")
        if name in dashboard_properties.lower()
    }
    template_fields = set(schemas["FaceTemplateResponse"]["properties"])
    assert {"model_name", "model_version", "quality_metadata", "created_at"} <= (
        template_fields
    )
    assert (
        not {
            "image",
            "image_blob",
            "embedding",
            "embedding_ciphertext",
        }
        & template_fields
    )
    assert (
        student_create["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/StudentCreateRequest"
    )
    for status_code in ("401", "403", "422", "501"):
        assert (
            student_create["responses"][status_code]["content"]["application/json"][
                "schema"
            ]["$ref"]
            == "#/components/schemas/ErrorEnvelope"
        )


def test_openapi_documents_master_data_detail_update_and_roster_contracts() -> None:
    document = app.openapi()
    paths = document["paths"]
    assert {
        "/api/v1/students/{student_id}",
        "/api/v1/classes/{class_id}",
        "/api/v1/classes/{class_id}/students",
        "/api/v1/classes/{class_id}/students/{student_id}",
        "/api/v1/laboratories/{laboratory_id}",
        "/api/v1/students/import/preview",
        "/api/v1/students/import/commit",
    } <= set(paths)
    assert "patch" in paths["/api/v1/students/{student_id}"]
    assert "patch" in paths["/api/v1/classes/{class_id}"]
    assert "patch" in paths["/api/v1/laboratories/{laboratory_id}"]
    schemas = document["components"]["schemas"]
    assert "classes" in schemas["StudentDetailResponse"]["properties"]
    assert "students" in schemas["ClassDetailResponse"]["properties"]
    assert "updated_at" in schemas["LaboratoryResponse"]["properties"]
    assert (
        "multipart/form-data"
        in paths["/api/v1/students/import/preview"]["post"]["requestBody"]["content"]
    )
    assert "StudentImportPreviewResponse" in schemas


def test_openapi_documents_device_heartbeat_contract() -> None:
    document = app.openapi()
    heartbeat = document["paths"]["/api/v1/devices/{device_id}/heartbeat"]["post"]
    assert (
        heartbeat["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/DeviceHeartbeatResponse"
    )
    assert (
        "last_seen_at"
        in document["components"]["schemas"]["DeviceHeartbeatResponse"]["properties"]
    )


def test_openapi_documents_oauth_password_login_and_bearer_auth() -> None:
    document = app.openapi()
    login = document["paths"]["/api/v1/auth/login"]["post"]
    authenticated_me = document["paths"]["/api/v1/auth/me"]["get"]

    assert "application/x-www-form-urlencoded" in login["requestBody"]["content"]
    assert authenticated_me["security"] == [{"OAuth2PasswordBearer": []}]
    password_flow = document["components"]["securitySchemes"]["OAuth2PasswordBearer"][
        "flows"
    ]["password"]
    assert password_flow["tokenUrl"] == "/api/v1/auth/login"


def test_schedule_endpoint_returns_empty_page_when_no_schedules_exist() -> None:
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
        id=UUID(int=1),
        email="admin@example.edu",
        full_name="Admin",
        roles=frozenset({RoleCode.ADMIN}),
    )
    try:
        response = send_request("GET", "/api/v1/schedules")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "pagination": {"total": 0, "limit": 50, "offset": 0},
    }


def test_http_not_found_uses_standard_error_envelope() -> None:
    response = send_request("GET", "/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "The requested resource was not found.",
        }
    }


def test_protected_endpoint_requires_bearer_authentication() -> None:
    response = send_request("GET", "/api/v1/students")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "unauthorized"
