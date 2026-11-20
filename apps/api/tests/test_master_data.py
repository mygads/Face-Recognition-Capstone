from __future__ import annotations

import asyncio
from collections.abc import Generator
from typing import cast
from uuid import UUID

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from presensi_api.api.security.dependencies import get_current_user
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
from presensi_api.db.base import Base
from presensi_api.db.models import (
    AuditLog,
    ClassStudent,
    Device,
    FaceTemplate,
    KioskScreen,
    Laboratory,
    SchoolClass,
    Student,
    User,
)
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
    with factory.begin() as session:
        session.add(
            User(
                id=UUID(int=42),
                email="admin@example.test",
                full_name="Test Admin",
                password_hash="unused-test-hash",
            )
        )
    principal = AuthenticatedUser(
        id=UUID(int=42),
        email="admin@example.test",
        full_name="Test Admin",
        roles=frozenset({RoleCode.ADMIN}),
    )
    app.dependency_overrides[get_current_user] = lambda: principal
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


def test_student_crud_search_pagination_and_soft_deactivation(
    api_database: sessionmaker[Session],
) -> None:
    created = request(
        "POST",
        "/api/v1/students",
        {"student_number": "  s-001 ", "full_name": "Synthetic Student"},
    )
    assert created.status_code == 201
    student = created.json()
    assert student["student_number"] == "S-001"
    assert student["is_active"] is True
    assert student["created_at"].endswith("Z") or "+00:00" in student["created_at"]

    duplicate = request(
        "POST",
        "/api/v1/students",
        {"student_number": "s-001", "full_name": "Duplicate"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_student_number"

    page = request("GET", "/api/v1/students?search=synthetic&limit=1&offset=0")
    assert page.status_code == 200
    assert page.json()["pagination"] == {"total": 1, "limit": 1, "offset": 0}
    assert page.json()["items"][0]["id"] == student["id"]

    detail = request("GET", f"/api/v1/students/{student['id']}")
    assert detail.status_code == 200
    assert detail.json()["classes"] == []

    updated = request(
        "PATCH",
        f"/api/v1/students/{student['id']}",
        {"full_name": "Updated Synthetic Student"},
    )
    assert updated.status_code == 200
    assert updated.json()["full_name"] == "Updated Synthetic Student"

    with api_database.begin() as session:
        session.add(
            FaceTemplate(
                student_id=UUID(student["id"]),
                model_name="synthetic-sface",
                model_version="test-v1",
                embedding_ciphertext=b"synthetic-encrypted-vector",
                encryption_key_id="test-key",
                embedding_dimension=3,
                quality_metadata={"quality": 0.9},
            )
        )

    deactivated = request(
        "PATCH", f"/api/v1/students/{student['id']}", {"is_active": False}
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    with api_database() as session:
        template = session.scalar(select(FaceTemplate))
        assert template is not None
        assert template.revoked_at is not None
        assert template.embedding_ciphertext is None
        assert template.encryption_key_id is None
        assert (
            session.scalar(
                select(AuditLog).where(AuditLog.action == "student.deactivated")
            )
            is not None
        )
        assert (
            session.scalar(
                select(AuditLog).where(
                    AuditLog.action == "face_template.revoked_on_student_deactivation"
                )
            )
            is not None
        )
    assert (
        request("GET", "/api/v1/students?is_active=true").json()["pagination"]["total"]
        == 0
    )
    assert (
        request("GET", "/api/v1/students?is_active=false").json()["pagination"]["total"]
        == 1
    )


def test_classes_laboratories_and_student_class_relationship(
    api_database: sessionmaker[Session],
) -> None:
    student = request(
        "POST",
        "/api/v1/students",
        {"student_number": "S-002", "full_name": "Roster Student"},
    ).json()
    school_class = request(
        "POST",
        "/api/v1/classes",
        {
            "code": "X-IPA-1",
            "name": "Kelas X IPA 1",
            "grade": 10,
            "academic_year": "2026-2027",
        },
    )
    assert school_class.status_code == 201
    class_data = school_class.json()

    membership = request(
        "POST",
        f"/api/v1/classes/{class_data['id']}/students",
        {"student_id": student["id"]},
    )
    assert membership.status_code == 201
    assert membership.json()["student_number"] == "S-002"
    duplicate_membership = request(
        "POST",
        f"/api/v1/classes/{class_data['id']}/students",
        {"student_id": student["id"]},
    )
    assert duplicate_membership.status_code == 409

    class_detail = request("GET", f"/api/v1/classes/{class_data['id']}")
    assert [row["id"] for row in class_detail.json()["students"]] == [student["id"]]
    student_detail = request("GET", f"/api/v1/students/{student['id']}")
    assert student_detail.json()["classes"][0]["id"] == class_data["id"]

    assert (
        request(
            "DELETE",
            f"/api/v1/classes/{class_data['id']}/students/{student['id']}",
        ).status_code
        == 204
    )
    with api_database() as session:
        removal_audit = session.scalar(
            select(AuditLog).where(
                AuditLog.action == "class.student_membership_removed"
            )
        )
        assert removal_audit is not None
    assert (
        request("GET", f"/api/v1/classes/{class_data['id']}").json()["students"] == []
    )

    laboratory = request(
        "POST",
        "/api/v1/laboratories",
        {"code": "LAB-A", "name": "Lab Kimia", "location": "Gedung A"},
    )
    assert laboratory.status_code == 201
    lab_data = laboratory.json()
    assert "updated_at" in lab_data
    updated = request(
        "PATCH",
        f"/api/v1/laboratories/{lab_data['id']}",
        {"location": None, "is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["location"] is None
    assert updated.json()["is_active"] is False
    listed = request("GET", "/api/v1/laboratories?search=kimia")
    assert listed.json()["pagination"]["total"] == 1


def test_student_filter_and_unique_active_class_membership_per_academic_year(
    api_database: sessionmaker[Session],
) -> None:
    student = request(
        "POST",
        "/api/v1/students",
        {"student_number": "S-YEAR-1", "full_name": "Academic Year Student"},
    ).json()

    def create_class(code: str, year: str, grade: int = 10) -> dict[str, object]:
        response = request(
            "POST",
            "/api/v1/classes",
            {
                "code": code,
                "name": f"Class {code}",
                "grade": grade,
                "academic_year": year,
            },
        )
        assert response.status_code == 201
        return cast(dict[str, object], response.json())

    class_a_id = str(create_class("YEAR-A", "2026-2027")["id"])
    class_b_id = str(create_class("YEAR-B", "2026-2027")["id"])
    next_year_id = str(create_class("YEAR-C", "2027-2028", grade=11)["id"])
    assert (
        request(
            "POST",
            f"/api/v1/classes/{class_a_id}/students",
            {"student_id": student["id"]},
        ).status_code
        == 201
    )

    conflict = request(
        "POST",
        f"/api/v1/classes/{class_b_id}/students",
        {"student_id": student["id"]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "student_already_in_class_year"
    assert (
        request(
            "POST",
            f"/api/v1/classes/{next_year_id}/students",
            {"student_id": student["id"]},
        ).status_code
        == 201
    )

    filtered = request("GET", f"/api/v1/students?class_id={class_a_id}")
    assert [row["id"] for row in filtered.json()["items"]] == [student["id"]]
    assert (
        request("GET", f"/api/v1/students?class_id={class_b_id}").json()["items"] == []
    )

    moved = request(
        "PUT", f"/api/v1/students/{student['id']}/class-memberships/{class_b_id}"
    )
    assert moved.status_code == 200
    memberships = request("GET", f"/api/v1/students/{student['id']}").json()["classes"]
    assert {row["id"] for row in memberships} == {class_b_id, next_year_id}
    with api_database() as session:
        assert (
            session.scalar(
                select(AuditLog).where(
                    AuditLog.action == "class.student_membership_moved",
                    AuditLog.entity_id == UUID(student["id"]),
                )
            )
            is not None
        )


def test_class_year_change_cannot_create_duplicate_active_membership(
    api_database: sessionmaker[Session],
) -> None:
    student = request(
        "POST",
        "/api/v1/students",
        {"student_number": "S-YEAR-2", "full_name": "Class Change Student"},
    ).json()
    class_a = request(
        "POST",
        "/api/v1/classes",
        {
            "code": "CHANGE-A",
            "name": "Change Class A",
            "grade": 10,
            "academic_year": "2026-2027",
        },
    ).json()
    class_b = request(
        "POST",
        "/api/v1/classes",
        {
            "code": "CHANGE-B",
            "name": "Change Class B",
            "grade": 11,
            "academic_year": "2027-2028",
        },
    ).json()
    for school_class in (class_a, class_b):
        assert (
            request(
                "POST",
                f"/api/v1/classes/{school_class['id']}/students",
                {"student_id": student["id"]},
            ).status_code
            == 201
        )

    changed = request(
        "PATCH",
        f"/api/v1/classes/{class_a['id']}",
        {"academic_year": "2027-2028"},
    )
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "class_year_membership_conflict"


def test_master_data_rejects_empty_patch_and_unknown_resources(
    api_database: sessionmaker[Session],
) -> None:
    student = request(
        "POST",
        "/api/v1/students",
        {"student_number": "S-003", "full_name": "Synthetic"},
    ).json()
    assert request("PATCH", f"/api/v1/students/{student['id']}", {}).status_code == 422
    assert (
        request(
            "GET", "/api/v1/students/00000000-0000-0000-0000-000000000001"
        ).status_code
        == 404
    )
    invalid_student = request(
        "POST",
        "/api/v1/students",
        {"student_number": "", "full_name": "Synthetic"},
    )
    assert invalid_student.status_code == 422
    assert invalid_student.json()["error"]["code"] == "validation_error"
    assert any(
        detail["field"] == "body.student_number"
        for detail in invalid_student.json()["error"]["details"]
    )


def test_device_delete_revokes_credentials_and_preserves_audited_history(
    api_database: sessionmaker[Session],
) -> None:
    laboratory = request(
        "POST", "/api/v1/laboratories", {"code": "LAB-DELETE", "name": "Delete Lab"}
    ).json()
    created = request(
        "POST",
        "/api/v1/devices",
        {
            "laboratory_id": laboratory["id"],
            "name": "Synthetic Device",
            "device_type": "edge_pc",
            "deployment_profile": "AI_EDGE",
        },
    )
    assert created.status_code == 201
    device_id = created.json()["device_id"]
    with api_database.begin() as session:
        device = session.get(Device, UUID(device_id))
        assert device is not None
        device.credential_hash = "current-verifier"
        device.credential_expires_at = None
        device.previous_credential_hash = "previous-verifier"
        device.previous_credential_expires_at = None

    deleted = request("DELETE", f"/api/v1/devices/{device_id}")
    assert deleted.status_code == 204
    assert request("DELETE", f"/api/v1/devices/{device_id}").status_code == 204

    with api_database() as session:
        device = session.get(Device, UUID(device_id))
        assert device is not None
        assert device.is_active is False
        assert device.credential_hash is None
        assert device.previous_credential_hash is None
        assert device.camera_status == "offline"
        assert (
            session.scalar(
                select(AuditLog).where(
                    AuditLog.action == "device.deactivated",
                    AuditLog.entity_id == UUID(device_id),
                )
            )
            is not None
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.action == "device.deactivated",
                    AuditLog.entity_id == UUID(device_id),
                )
            )
            == 1
        )
        assert session.get(Laboratory, UUID(laboratory["id"])) is not None

    active_devices = request("GET", "/api/v1/devices?is_active=true")
    archived_devices = request("GET", "/api/v1/devices?is_active=false")
    assert active_devices.json()["pagination"]["total"] == 0
    assert archived_devices.json()["pagination"]["total"] == 1


def test_device_can_be_permanently_deleted_only_when_no_history_or_kiosk_exists(
    api_database: sessionmaker[Session],
) -> None:
    laboratory = request(
        "POST", "/api/v1/laboratories", {"code": "LAB-PURGE", "name": "Purge Lab"}
    ).json()

    def create_device(name: str) -> str:
        response = request(
            "POST",
            "/api/v1/devices",
            {
                "laboratory_id": laboratory["id"],
                "name": name,
                "device_type": "edge_pc",
                "deployment_profile": "AI_EDGE",
            },
        )
        assert response.status_code == 201
        return str(response.json()["device_id"])

    removable_id = create_device("Removable Device")
    assert (
        request("DELETE", f"/api/v1/devices/{removable_id}?permanent=true").status_code
        == 409
    )
    assert request("DELETE", f"/api/v1/devices/{removable_id}").status_code == 204
    assert (
        request("DELETE", f"/api/v1/devices/{removable_id}?permanent=true").status_code
        == 204
    )
    with api_database() as session:
        assert session.get(Device, UUID(removable_id)) is None
        assert (
            session.scalar(
                select(AuditLog).where(
                    AuditLog.action == "device.permanently_deleted",
                    AuditLog.entity_id == UUID(removable_id),
                )
            )
            is not None
        )

    retained_id = create_device("Kiosk Device")
    assert request("DELETE", f"/api/v1/devices/{retained_id}").status_code == 204
    with api_database.begin() as session:
        session.add(
            KioskScreen(
                device_id=UUID(retained_id),
                laboratory_id=UUID(str(laboratory["id"])),
                display_name="Retained Kiosk",
            )
        )
    blocked = request("DELETE", f"/api/v1/devices/{retained_id}?permanent=true")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "device_has_history"
    assert (
        request("GET", "/api/v1/devices?is_active=false").json()["pagination"]["total"]
        == 1
    )


def test_student_search_treats_percent_and_underscore_literally(
    api_database: "sessionmaker[Session]",
) -> None:
    first = request(
        "POST",
        "/api/v1/students",
        {"student_number": "100%", "full_name": "Percent Student"},
    )
    assert first.status_code == 201
    second = request(
        "POST",
        "/api/v1/students",
        {"student_number": "100A", "full_name": "Hundred A Student"},
    )
    assert second.status_code == 201

    page = request("GET", "/api/v1/students?search=100%25")
    assert page.status_code == 200
    numbers = [item["student_number"] for item in page.json()["items"]]
    assert numbers == ["100%"]

    third = request(
        "POST",
        "/api/v1/students",
        {"student_number": "A_1", "full_name": "Underscore Student"},
    )
    assert third.status_code == 201
    fourth = request(
        "POST",
        "/api/v1/students",
        {"student_number": "AX1", "full_name": "Ex Student"},
    )
    assert fourth.status_code == 201

    underscore = request("GET", "/api/v1/students?search=A_1")
    assert underscore.status_code == 200
    assert [item["student_number"] for item in underscore.json()["items"]] == ["A_1"]


def test_student_delete_archives_biometric_history_and_deletes_unused_records(
    api_database: sessionmaker[Session],
) -> None:
    unused = request(
        "POST",
        "/api/v1/students",
        {"student_number": "S-UNUSED", "full_name": "Unused Synthetic Student"},
    ).json()
    deleted = request("DELETE", f"/api/v1/students/{unused['id']}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["action"] == "deleted"
    with api_database() as session:
        assert session.get(Student, UUID(unused["id"])) is None

    referenced = request(
        "POST",
        "/api/v1/students",
        {"student_number": "S-RETAIN", "full_name": "Retained Synthetic Student"},
    ).json()
    template_id = UUID(int=901)
    with api_database.begin() as session:
        session.add(
            FaceTemplate(
                id=template_id,
                student_id=UUID(referenced["id"]),
                model_name="synthetic-fixture",
                model_version="v1",
                embedding_ciphertext=b"synthetic-test-embedding",
                encryption_key_id="test-key",
                embedding_dimension=2,
                created_by_user_id=UUID(int=42),
            )
        )

    archived = request("DELETE", f"/api/v1/students/{referenced['id']}")
    assert archived.status_code == 200, archived.text
    assert archived.json()["action"] == "archived"
    with api_database() as session:
        retained = session.get(Student, UUID(referenced["id"]))
        template = session.get(FaceTemplate, template_id)
        assert retained is not None and retained.is_active is False
        assert template is not None and template.revoked_at is not None
        assert template.embedding_ciphertext is None


def test_class_delete_archives_class_membership_and_hard_deletes_unused_class(
    api_database: sessionmaker[Session],
) -> None:
    unused = request(
        "POST",
        "/api/v1/classes",
        {
            "code": "UNUSED",
            "name": "Unused Synthetic Class",
            "grade": 10,
            "academic_year": "2026-2027",
        },
    ).json()
    deleted = request("DELETE", f"/api/v1/classes/{unused['id']}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["action"] == "deleted"
    with api_database() as session:
        assert session.get(SchoolClass, UUID(unused["id"])) is None

    retained = request(
        "POST",
        "/api/v1/classes",
        {
            "code": "RETAIN",
            "name": "Retained Synthetic Class",
            "grade": 11,
            "academic_year": "2026-2027",
        },
    ).json()
    student = request(
        "POST",
        "/api/v1/students",
        {"student_number": "S-MEMBER", "full_name": "Synthetic Class Member"},
    ).json()
    with api_database.begin() as session:
        session.add(
            ClassStudent(class_id=UUID(retained["id"]), student_id=UUID(student["id"]))
        )

    archived = request("DELETE", f"/api/v1/classes/{retained['id']}")
    assert archived.status_code == 200, archived.text
    assert archived.json()["action"] == "archived"
    with api_database() as session:
        retained_class = session.get(SchoolClass, UUID(retained["id"]))
        membership = session.get(
            ClassStudent, (UUID(retained["id"]), UUID(student["id"]))
        )
        assert retained_class is not None and retained_class.is_active is False
        assert membership is not None
