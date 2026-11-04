from __future__ import annotations

import asyncio
from collections.abc import Generator
from pathlib import Path
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
    assert "delete" in document["paths"]["/api/v1/devices/{device_id}"]
    device_query_fields = {
        parameter["name"]
        for parameter in document["paths"]["/api/v1/devices"]["get"]["parameters"]
    }
    assert {"deployment_profile", "is_active"} <= device_query_fields
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
    assert "enrollment_model_version" in schemas["AiReadinessResponse"]["properties"]
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
    change_password = document["paths"]["/api/v1/auth/change-password"]["post"]

    assert "application/x-www-form-urlencoded" in login["requestBody"]["content"]
    assert authenticated_me["security"] == [{"OAuth2PasswordBearer": []}]
    password_flow = document["components"]["securitySchemes"]["OAuth2PasswordBearer"][
        "flows"
    ]["password"]
    assert password_flow["tokenUrl"] == "/api/v1/auth/login"
    assert (
        change_password["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/PasswordChangeRequest"
    )


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


def test_openapi_documents_device_queue_status_in_heartbeat() -> None:
    document = app.openapi()
    heartbeat_path = "/api/v1/devices/{device_id}/device-heartbeat"
    heartbeat = document["paths"][heartbeat_path]["post"]
    body_schema = heartbeat["requestBody"]["content"]["application/json"]["schema"]
    refs = [
        option.get("$ref")
        for option in body_schema.get("anyOf", [body_schema])
        if isinstance(option, dict)
    ]
    assert "#/components/schemas/DeviceHeartbeatRequest" in refs
    heartbeat_schema = document["components"]["schemas"]["DeviceHeartbeatRequest"]
    queue_prop = heartbeat_schema["properties"]["queue_status"]
    queue_options = queue_prop.get("anyOf", [queue_prop])
    assert any(
        isinstance(option, dict)
        and option.get("$ref") == "#/components/schemas/DeviceQueueStatus"
        for option in queue_options
    )
    queue_schema = document["components"]["schemas"]["DeviceQueueStatus"]["properties"]
    assert set(queue_schema) == {"pending_events", "dead_letter_events"}
    device_schema = document["components"]["schemas"]["DeviceResponse"]["properties"]
    assert {"pending_events", "dead_letter_events", "queue_updated_at"} <= set(
        device_schema
    )


def _generated_web_schema() -> str:
    schema_path = (
        Path(__file__).resolve().parents[3]
        / "apps"
        / "web"
        / "src"
        / "api"
        / "generated"
        / "schema.d.ts"
    )
    return schema_path.read_text(encoding="utf-8")


def _slice_block(marker: str, text: str, *end_markers: str) -> str:
    """Slice a generated block from its marker to the next sibling key."""
    start = text.index(marker)
    rest = text[start + len(marker) :]
    positions = [rest.index(end) for end in end_markers if end in rest]
    assert positions, f"no block end after {marker!r}"
    return rest[: min(positions)]


def test_generated_web_schema_matches_openapi_contract() -> None:
    """The checked-in TypeScript schema must mirror the served OpenAPI.

    ``schema.d.ts`` is touched by hand between ``npm run api:generate``
    runs, so a forgotten regen makes the teacher UI lie about routes,
    operations, and response fields. The failure names the exact missing
    piece; regenerate instead of hand-editing when it fires.
    """
    document = app.openapi()
    schema = _generated_web_schema()

    missing_routes: list[str] = []
    for path, item in document["paths"].items():
        marker = f'    "{path}": {{'
        if marker not in schema:
            missing_routes.append(path)
            continue
        block = _slice_block(marker, schema, '\n    "', "\n}")
        methods = [method for method in item if method != "parameters"]
        missing_routes.extend(
            f"{method.upper()} {path}"
            for method in methods
            if f"\n        {method}:" not in block
        )

    missing_operations: list[str] = []
    for item in document["paths"].values():
        for method, operation in item.items():
            if method == "parameters" or not isinstance(operation, dict):
                continue
            operation_id = str(operation.get("operationId", ""))
            if f"\n    {operation_id}: {{" not in schema:
                missing_operations.append(operation_id)

    missing_fields: list[str] = []
    schemas = document["components"]["schemas"]
    for name, definition in schemas.items():
        marker = f"\n        {name}: {{"
        if marker not in schema:
            missing_fields.append(name)
            continue
        block = _slice_block(marker, schema, "\n        /**", "\n    };")
        for prop in definition.get("properties", {}):
            found = block.find(f"\n            {prop}")
            prop_end = found + len("\n            ") + len(prop)
            if found < 0 or block[prop_end] not in "?: ":
                missing_fields.append(f"{name}.{prop}")

    assert missing_routes == [], f"web schema misses routes: {missing_routes}"
    assert missing_operations == [], (
        f"web schema misses operations: {missing_operations}"
    )
    assert missing_fields == [], f"web schema misses fields: {missing_fields}"
