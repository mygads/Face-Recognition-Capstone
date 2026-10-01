from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Generator
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from presensi_api.api.security.dependencies import get_current_user
from presensi_api.api.security.request_rate_limit import SlidingWindowRateLimiter
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
from presensi_api.db.base import Base
from presensi_api.db.models import (
    AuditLog,
    ClassStudent,
    FaceTemplate,
    SchoolClass,
    Student,
    User,
)
from presensi_api.db.session import get_db_session
from presensi_api.enrollment_processing import (
    EnrollmentFrameResult,
    get_enrollment_processor,
)
from presensi_api.main import app

OPERATOR_ID = UUID("c8939f05-b76a-4f6f-bf5c-7e0f326c56c1")
TARGET_STUDENT_ID = UUID("994548ad-b426-4b6c-9e9b-28251268ac20")
DUPLICATE_STUDENT_ID = UUID("e4a9424d-8b9b-41dc-8e8b-d821649788a6")
CLASS_ID = UUID("d8246302-3c60-4517-b5ae-e76f69b0e641")


class SyntheticEnrollmentProcessor:
    def __init__(self, *, reject_last: bool = False, accept_count: int = 10) -> None:
        self.reject_last = reject_last
        self.accept_count = accept_count
        self.calls = 0

    def process(
        self, image_bytes: bytes, *, model_version: str
    ) -> EnrollmentFrameResult:
        del model_version
        self.calls += 1
        capture_number = image_bytes[0]
        accepted = capture_number < self.accept_count and not (
            self.reject_last and capture_number == 4
        )
        score = 0.7 + capture_number / 10
        return EnrollmentFrameResult(
            accepted=accepted,
            model_name="synthetic-sface",
            model_version="synthetic-v1",
            embedding=(1.0, 0.0, 0.0) if accepted else None,
            quality_score=score if accepted else 0.0,
            quality_metadata={"score": score, "accepted": accepted},
            reason=None if accepted else "quality_rejected",
        )


@pytest.fixture
def enrollment_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[sessionmaker[Session], SyntheticEnrollmentProcessor], None, None]:
    monkeypatch.setenv(
        "PRESENSI_FACE_TEMPLATE_KEYS",
        json.dumps({"test-v1": base64.b64encode(b"t" * 32).decode("ascii")}),
    )
    monkeypatch.setenv("PRESENSI_FACE_TEMPLATE_ACTIVE_KEY_ID", "test-v1")
    monkeypatch.setenv("PRESENSI_ENROLLMENT_DUPLICATE_WARNING_THRESHOLD", "0.9")
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

    processor = SyntheticEnrollmentProcessor(reject_last=True)
    app.dependency_overrides[get_db_session] = override_db
    app.state.request_rate_limiter = SlidingWindowRateLimiter()
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=OPERATOR_ID,
        email="laborant@example.test",
        full_name="Synthetic Laborant",
        roles=frozenset({RoleCode.LABORANT}),
    )
    app.dependency_overrides[get_enrollment_processor] = lambda: processor
    with factory.begin() as session:
        school_class = SchoolClass(
            id=CLASS_ID,
            code="X-SYNTH",
            name="Synthetic Class",
            grade=10,
            academic_year="2026-2027",
        )
        student = Student(
            id=TARGET_STUDENT_ID,
            student_number="S-001",
            full_name="Synthetic Target",
        )
        session.add_all(
            [
                school_class,
                User(
                    id=OPERATOR_ID,
                    email="laborant@example.test",
                    full_name="Synthetic Laborant",
                    password_hash="unused-test-hash",
                ),
                student,
                Student(
                    id=DUPLICATE_STUDENT_ID,
                    student_number="S-002",
                    full_name="Synthetic Lookalike",
                ),
            ]
        )
        session.flush()
        session.add(ClassStudent(class_id=CLASS_ID, student_id=TARGET_STUDENT_ID))
    try:
        yield factory, processor
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _request(
    method: str,
    path: str,
    *,
    data: dict[str, str] | None = None,
    files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.request(method, path, data=data, files=files)

    return asyncio.run(send())


def _captures(count: int = 5) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [
        (
            "captures",
            (
                f"capture-{index}.jpg",
                bytes([index]) + b"-synthetic-private-frame",
                "image/jpeg",
            ),
        )
        for index in range(count)
    ]


def test_multiple_captures_create_encrypted_templates_and_duplicate_warning(
    enrollment_runtime: tuple[sessionmaker[Session], SyntheticEnrollmentProcessor],
    caplog: pytest.LogCaptureFixture,
) -> None:
    factory, processor = enrollment_runtime
    from presensi_api.biometric_crypto import FaceTemplateKeyring

    keyring = FaceTemplateKeyring.from_environment()
    existing_id = uuid4()
    existing_batch = uuid4()
    encrypted = keyring.encrypt(
        (1.0, 0.0, 0.0),
        template_id=existing_id,
        student_id=DUPLICATE_STUDENT_ID,
        model_name="synthetic-sface",
        model_version="synthetic-v1",
    )
    with factory.begin() as session:
        session.add(
            FaceTemplate(
                id=existing_id,
                student_id=DUPLICATE_STUDENT_ID,
                enrollment_batch_id=existing_batch,
                model_name="synthetic-sface",
                model_version="synthetic-v1",
                embedding_ciphertext=encrypted.ciphertext,
                encryption_key_id=encrypted.key_id,
                embedding_dimension=encrypted.dimension,
                quality_metadata={"score": 0.9},
            )
        )

    response = _request(
        "POST",
        "/api/v1/enrollments/captures",
        data={"student_id": str(TARGET_STUDENT_ID)},
        files=_captures(),
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["accepted_frames"] == 4
    assert payload["rejected_frames"] == 1
    assert payload["template_count"] == 4
    assert payload["duplicate_warnings"][0]["student_id"] == str(DUPLICATE_STUDENT_ID)
    assert payload["confirmation_required"] is True
    assert "embedding" not in response.text
    assert "ciphertext" not in response.text
    assert "synthetic-private-frame" not in caplog.text
    assert processor.calls == 5
    with factory() as session:
        templates = session.scalars(
            select(FaceTemplate).where(
                FaceTemplate.student_id == TARGET_STUDENT_ID,
                FaceTemplate.revoked_at.is_(None),
            )
        ).all()
        assert len(templates) == 4
        assert all(
            row.embedding_ciphertext is not None
            and b"-synthetic-private-frame" not in row.embedding_ciphertext
            for row in templates
        )
        audit = session.scalar(
            select(AuditLog).where(AuditLog.action == "face_template.enrolled")
        )
        assert audit is not None
        audit_json = json.dumps(audit.after_state)
        assert "embedding" not in audit_json
        assert "ciphertext" not in audit_json


def test_revoke_enrollment_batch_allows_reenrollment(
    enrollment_runtime: tuple[sessionmaker[Session], SyntheticEnrollmentProcessor],
) -> None:
    factory, _processor = enrollment_runtime
    created = _request(
        "POST",
        "/api/v1/enrollments/captures",
        data={"student_id": str(TARGET_STUDENT_ID)},
        files=_captures(4),
    )
    assert created.status_code == 201
    template_page = _request(
        "GET", f"/api/v1/face-templates?student_id={TARGET_STUDENT_ID}"
    )
    assert template_page.status_code == 200
    template_id = template_page.json()["items"][0]["id"]

    revoked = _request("POST", f"/api/v1/face-templates/{template_id}/revoke")

    assert revoked.status_code == 200
    assert revoked.json()["revoked_templates"] == 4
    with factory() as session:
        revoked_templates = session.scalars(
            select(FaceTemplate).where(
                FaceTemplate.student_id == TARGET_STUDENT_ID,
                FaceTemplate.revoked_at.is_not(None),
            )
        ).all()
        assert len(revoked_templates) == 4
        assert all(
            template.embedding_ciphertext is None for template in revoked_templates
        )
        assert all(template.encryption_key_id is None for template in revoked_templates)
        revoke_audit = session.scalar(
            select(AuditLog).where(AuditLog.action == "face_template.revoked")
        )
        assert revoke_audit is not None
    class_status = _request(
        "GET", f"/api/v1/enrollments/class-status?class_id={CLASS_ID}"
    )
    assert class_status.status_code == 200
    assert class_status.json()[0]["template_status"] == "needs_reenrollment"
    re_enrolled = _request(
        "POST",
        "/api/v1/enrollments/captures",
        data={"student_id": str(TARGET_STUDENT_ID)},
        files=_captures(4),
    )
    assert re_enrolled.status_code == 201
    assert re_enrolled.json()["template_count"] == 4
    with factory() as session:
        active = session.scalars(
            select(FaceTemplate).where(
                FaceTemplate.student_id == TARGET_STUDENT_ID,
                FaceTemplate.revoked_at.is_(None),
            )
        ).all()
        assert len(active) == 4


def test_template_metadata_route_is_rate_limited_per_operator(
    enrollment_runtime: tuple[sessionmaker[Session], SyntheticEnrollmentProcessor],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app.state, "enrollment_requests_per_minute", 1)

    first = _request("GET", "/api/v1/face-templates")
    second = _request("GET", "/api/v1/face-templates")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "enrollment_rate_limit_exceeded"


def test_active_template_keys_can_be_rotated_in_batches(
    enrollment_runtime: tuple[sessionmaker[Session], SyntheticEnrollmentProcessor],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, _processor = enrollment_runtime
    created = _request(
        "POST",
        "/api/v1/enrollments/captures",
        data={"student_id": str(TARGET_STUDENT_ID)},
        files=_captures(4),
    )
    assert created.status_code == 201

    monkeypatch.setenv(
        "PRESENSI_FACE_TEMPLATE_KEYS",
        json.dumps(
            {
                "test-v1": base64.b64encode(b"t" * 32).decode("ascii"),
                "test-v2": base64.b64encode(b"n" * 32).decode("ascii"),
            }
        ),
    )
    monkeypatch.setenv("PRESENSI_FACE_TEMPLATE_ACTIVE_KEY_ID", "test-v2")
    from presensi_api import biometric_key_rotation

    monkeypatch.setattr(biometric_key_rotation, "get_session_factory", lambda: factory)
    assert biometric_key_rotation.rotate_active_template_keys(batch_size=2) == 4

    from presensi_api.biometric_crypto import FaceTemplateKeyring

    keyring = FaceTemplateKeyring.from_environment()
    with factory() as session:
        active = session.scalars(
            select(FaceTemplate).where(
                FaceTemplate.student_id == TARGET_STUDENT_ID,
                FaceTemplate.revoked_at.is_(None),
            )
        ).all()
        assert len(active) == 4
        assert all(item.encryption_key_id == "test-v2" for item in active)
        assert all(
            keyring.decrypt(
                item.embedding_ciphertext or b"",
                dimension=item.embedding_dimension or 0,
                key_id=item.encryption_key_id or "",
                template_id=item.id,
                student_id=item.student_id,
                model_name=item.model_name,
                model_version=item.model_version,
            )
            == pytest.approx((1.0, 0.0, 0.0))
            for item in active
        )


def test_low_quality_frames_and_incompatible_uploads_store_nothing(
    enrollment_runtime: tuple[sessionmaker[Session], SyntheticEnrollmentProcessor],
) -> None:
    factory, processor = enrollment_runtime
    processor.accept_count = 2
    insufficient = _request(
        "POST",
        "/api/v1/enrollments/captures",
        data={"student_id": str(TARGET_STUDENT_ID)},
        files=_captures(4),
    )
    assert insufficient.status_code == 422
    assert insufficient.json()["error"]["code"] == "insufficient_quality_captures"

    oversized = _request(
        "POST",
        "/api/v1/enrollments/captures",
        data={"student_id": str(TARGET_STUDENT_ID)},
        files=[
            (
                "captures",
                ("large.jpg", b"x" * (3 * 1024 * 1024 + 1), "image/jpeg"),
            ),
            *(_captures(2)),
        ],
    )
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "capture_too_large"

    unsupported = _request(
        "POST",
        "/api/v1/enrollments/captures",
        data={"student_id": str(TARGET_STUDENT_ID)},
        files=[("captures", ("capture.gif", b"fixture", "image/gif"))] * 3,
    )
    assert unsupported.status_code == 415
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(FaceTemplate)) == 0
