from __future__ import annotations

import asyncio
from uuid import UUID

import httpx

from presensi_api.api.security.dependencies import get_current_user
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
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
        "/api/v1/schedules",
        "/api/v1/sessions",
        "/api/v1/enrollments",
        "/api/v1/face-templates",
        "/api/v1/attendance",
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
    template_fields = set(schemas["FaceTemplateResponse"]["properties"])
    assert {"model_name", "model_version", "quality_metadata", "created_at"} <= (
        template_fields
    )
    assert not {"image", "image_blob", "embedding"} & template_fields
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
    } <= set(paths)
    assert "patch" in paths["/api/v1/students/{student_id}"]
    assert "patch" in paths["/api/v1/classes/{class_id}"]
    assert "patch" in paths["/api/v1/laboratories/{laboratory_id}"]
    schemas = document["components"]["schemas"]
    assert "classes" in schemas["StudentDetailResponse"]["properties"]
    assert "students" in schemas["ClassDetailResponse"]["properties"]
    assert "updated_at" in schemas["LaboratoryResponse"]["properties"]


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


def test_placeholder_returns_standard_error_envelope() -> None:
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

    assert response.status_code == 501
    assert response.json() == {
        "error": {
            "code": "feature_not_implemented",
            "message": (
                "The practicum schedules API is a contract placeholder and is "
                "not implemented."
            ),
        }
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


def test_request_validation_uses_standard_error_envelope() -> None:
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=UUID(int=1),
        email="admin@example.edu",
        full_name="Admin",
        roles=frozenset({RoleCode.ADMIN}),
    )
    try:
        response = send_request("POST", "/api/v1/students", {"student_number": ""})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert any(
        detail["field"] == "body.student_number" for detail in body["error"]["details"]
    )
