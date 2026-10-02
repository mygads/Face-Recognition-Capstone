from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest

from presensi_edge_agent import camera as camera_module
from presensi_edge_agent import cli as cli_module
from presensi_edge_agent.api import ApiCallError, ApiHealth, CoreApiClient
from presensi_edge_agent.cache import (
    ActiveSessionCache,
    CachedStudent,
    CacheSchemaError,
    SessionCacheBundle,
    parse_session_cache,
)
from presensi_edge_agent.config import (
    ApiSettings,
    CameraSettings,
    EdgeConfig,
    EdgeConfigError,
    LivenessSettings,
    ModelSettings,
    QualitySettings,
    RecognitionSettings,
    RuntimeSettings,
    load_config,
)
from presensi_edge_agent.events import event_payload
from presensi_edge_agent.logging import JsonLogFormatter
from presensi_edge_agent.managed_config import apply_managed_configuration
from presensi_edge_agent.outbox import (
    EventOutbox,
    OutboxEventConflict,
    OutboxFullError,
)
from presensi_edge_agent.recognition import LocalRecognizer
from presensi_edge_agent.service import EdgeService
from recognition_core.domain import (
    FaceEmbedding,
    GalleryEntry,
    RecognitionDecision,
    TrackDecision,
)

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_CONFIG = ROOT / "apps" / "edge-agent" / "config" / "edge-agent.example.yaml"
DEVICE_ID = UUID("33000000-0000-4000-8000-000000000001")
SESSION_ID = UUID("33000000-0000-4000-8000-000000000002")
STUDENT_ID = UUID("33000000-0000-4000-8000-000000000003")
MODEL_NAME = "opencv-zoo-sface"
MODEL_VERSION = "test-version"


def sample_bundle_payload(
    *,
    now: datetime | None = None,
    device_id: UUID = DEVICE_ID,
    model_version: str = MODEL_VERSION,
) -> dict[str, object]:
    created_at = now or datetime.now(UTC)
    return {
        "device_id": str(device_id),
        "session_id": str(SESSION_ID),
        "session_status": "active",
        "generated_at": created_at.isoformat(),
        "session_ends_at": (created_at + timedelta(hours=2)).isoformat(),
        "expires_at": (created_at + timedelta(minutes=1)).isoformat(),
        "model_name": MODEL_NAME,
        "model_version": model_version,
        "roster": [
            {
                "student_id": str(STUDENT_ID),
                "student_number": "SYN-01",
                "full_name": "Synthetic Student",
                "templates": [
                    {
                        "model_name": MODEL_NAME,
                        "model_version": model_version,
                        "normalized": True,
                        "values": [1.0, 0.0, 0.0],
                    }
                ],
            },
            {
                "student_id": "33000000-0000-4000-8000-000000000004",
                "student_number": "SYN-02",
                "full_name": "Not Enrolled",
                "templates": [],
            },
        ],
    }


def test_yaml_config_accepts_environment_overrides_without_a_secret_in_yaml() -> None:
    config = load_config(
        EXAMPLE_CONFIG,
        environ={
            "PRESENSI_EDGE_DEVICE_ID": str(DEVICE_ID),
            "PRESENSI_EDGE_CAMERA_INDEX": "2",
            "PRESENSI_EDGE_SAMPLE_EVERY_N_FRAMES": "7",
            "PRESENSI_EDGE_CACHE_MAX_OFFLINE_SECONDS": "90",
            "PRESENSI_EDGE_API_TOKEN": "test-token-is-in-environment-only",
        },
    )

    assert config.device_id == DEVICE_ID
    assert config.camera.index == 2
    assert config.camera.width == 1920
    assert config.camera.height == 1080
    assert config.recognition.sample_every_n_frames == 7
    assert config.api.cache_max_offline_seconds == 90
    assert config.recognition.min_top1_similarity is None
    assert "test-token-is-in-environment-only" not in repr(config)


def test_runtime_config_requires_calibrated_thresholds_and_model_files(
    tmp_path: Path,
) -> None:
    config = load_config(
        EXAMPLE_CONFIG, environ={"PRESENSI_EDGE_DEVICE_ID": str(DEVICE_ID)}
    )

    with pytest.raises(EdgeConfigError, match="API_TOKEN"):
        config.require_runtime(api_token=None)
    # Provision dummy local paths so this check reaches the calibration guard.
    fake_model_path = tmp_path / "unused-model-test.onnx"
    fake_model_path.write_bytes(b"not-a-real-model")
    model_config = replace(
        config.models,
        yunet_path=fake_model_path,
        sface_path=fake_model_path,
    )
    config = replace(config, models=model_config)
    with pytest.raises(EdgeConfigError, match="thresholds"):
        config.require_runtime(api_token="injected-test-token")


def test_status_allows_safe_edge_start_while_thresholds_wait_for_calibration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = load_config(
        EXAMPLE_CONFIG, environ={"PRESENSI_EDGE_DEVICE_ID": str(DEVICE_ID)}
    )
    model_path = tmp_path / "model.onnx"
    model_path.write_bytes(b"synthetic model placeholder")
    config = replace(
        config,
        models=replace(
            config.models,
            yunet_path=model_path,
            sface_path=model_path,
        ),
    )

    class FakeApi:
        def health(self) -> ApiHealth:
            return ApiHealth(reachable=True, status_code=200)

        def fetch_active_session_cache(self) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(cli_module, "load_cached_configuration", lambda item: item)
    monkeypatch.setattr(cli_module, "_api_client", lambda _config: FakeApi())
    monkeypatch.setattr(cli_module, "_camera_indices", lambda _config: [0])
    monkeypatch.setattr(
        cli_module, "resolve_api_token", lambda _config: "synthetic-token"
    )
    monkeypatch.setattr(cli_module, "resolve_ai_token", lambda _config: None)

    exit_code = cli_module._diagnostics(config, include_cameras=True)

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result["status"] == "waiting_for_calibration"
    assert result["runtime_ready"] is True
    assert result["recognition_ready"] is False
    assert result["selected_camera_available"] is True
    assert result["configuration_error"] is None


def test_managed_edge_defaults_can_apply_without_enabling_recognition() -> None:
    config = load_config(
        EXAMPLE_CONFIG, environ={"PRESENSI_EDGE_DEVICE_ID": str(DEVICE_ID)}
    )
    settings: dict[str, object] = {
        "min_face_pixels": 80,
        "min_laplacian_variance": 45.0,
        "min_brightness": 25.0,
        "max_brightness": 235.0,
        "min_top1_similarity": None,
        "min_top1_top2_margin": None,
        "minimum_agreeing_frames": 3,
        "sample_every_n_frames": 5,
        "best_frame_count": 5,
        "max_history_frames": 10,
        "calibration_reference": None,
    }

    updated = apply_managed_configuration(config, revision=1, settings=settings)
    recognizer = LocalRecognizer(None, DEVICE_ID)
    recognizer.apply_configuration(updated)

    assert updated.runtime_config_revision == 1
    assert updated.quality.min_face_pixels == 80
    assert updated.recognition.sample_every_n_frames == 5
    assert updated.recognition.min_top1_similarity is None
    assert updated.recognition.min_top1_top2_margin is None
    assert recognizer.pipeline is None


def test_managed_edge_config_rejects_partial_or_uncalibrated_thresholds() -> None:
    config = load_config(
        EXAMPLE_CONFIG, environ={"PRESENSI_EDGE_DEVICE_ID": str(DEVICE_ID)}
    )
    settings: dict[str, object] = {
        "min_face_pixels": 80,
        "min_laplacian_variance": 45.0,
        "min_brightness": 25.0,
        "max_brightness": 235.0,
        "min_top1_similarity": 0.7,
        "min_top1_top2_margin": None,
        "minimum_agreeing_frames": 3,
        "sample_every_n_frames": 5,
        "best_frame_count": 5,
        "max_history_frames": 10,
        "calibration_reference": None,
    }

    with pytest.raises(EdgeConfigError, match="not usable"):
        apply_managed_configuration(config, revision=1, settings=settings)

    settings["min_top1_top2_margin"] = 0.12
    with pytest.raises(EdgeConfigError, match="not usable"):
        apply_managed_configuration(config, revision=1, settings=settings)


def test_local_calibration_sample_never_enqueues_attendance(
    tmp_path: Path,
) -> None:
    config = load_config(
        EXAMPLE_CONFIG, environ={"PRESENSI_EDGE_DEVICE_ID": str(DEVICE_ID)}
    )
    bundle = parse_session_cache(
        sample_bundle_payload(),
        device_id=DEVICE_ID,
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
    )

    class FakeCamera:
        def open(self) -> None: ...

        def read(self) -> tuple[bool, object | None]:
            return False, None

        def close(self) -> None: ...

    class FakeApi:
        def close(self) -> None: ...

    class FakeRecognizer:
        process_calls = 0

        def process(self, _frame, _gallery, _captured_at) -> TrackDecision:
            self.process_calls += 1
            raise AssertionError("Diagnostic frames must bypass live recognition.")

        def reset(self) -> None: ...

    class DiagnosticRecognizer:
        process_calls = 0
        reset_calls = 0

        def process(self, _frame, _gallery, _captured_at) -> TrackDecision:
            self.process_calls += 1
            return TrackDecision(
                track_id="local-diagnostic",
                state="accepted",
                decision=RecognitionDecision(
                    outcome="matched",
                    student_id=STUDENT_ID,
                    confidence=0.9,
                    margin=0.1,
                ),
                observation_count=3,
            )

        def reset(self) -> None:
            self.reset_calls += 1

    outbox = EventOutbox(tmp_path / "diagnostic-outbox.sqlite3", max_pending=10)
    normal_recognizer = FakeRecognizer()
    service = EdgeService(
        config,
        FakeCamera(),
        FakeApi(),  # type: ignore[arg-type]
        outbox,
        normal_recognizer,  # type: ignore[arg-type]
        lambda: {},
    )
    diagnostic_recognizer = DiagnosticRecognizer()
    service._create_calibration_recognizer = lambda: diagnostic_recognizer  # type: ignore[method-assign]
    service.cache.replace(bundle)
    try:
        service._process_frame(object())
        assert service.preview is not None
        service.preview.update_status(camera_open=True, session_active=True)
        assert (
            service.preview.request_calibration_sample("genuine", str(STUDENT_ID))
            is None
        )

        service._process_frame(object())

        assert diagnostic_recognizer.process_calls == 1
        assert diagnostic_recognizer.reset_calls == 1
        assert normal_recognizer.process_calls == 0
        assert outbox.counts() == (0, 0)
        calibration = service.preview.status()["calibration"]
        assert isinstance(calibration, dict)
        assert calibration["genuine"]["sample_count"] == 1
        assert calibration["genuine"]["identity_match_count"] == 1
    finally:
        outbox.close()


def test_config_rejects_liveness_required_without_enabling_it(tmp_path: Path) -> None:
    config_path = tmp_path / "edge.yaml"
    config_path.write_text(
        "liveness:\n  enabled: false\n  required: true\n", encoding="utf-8"
    )
    with pytest.raises(EdgeConfigError, match="Required liveness"):
        load_config(config_path, environ={})


def test_core_api_client_uses_bearer_header_for_heartbeat_and_event() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "ok"})

    http = httpx.Client(
        base_url="https://api.example.test",
        transport=httpx.MockTransport(respond),
    )
    client = CoreApiClient(
        ApiSettings(
            base_url="https://api.example.test",
            timeout_seconds=1,
            heartbeat_interval_seconds=5,
            cache_refresh_seconds=3,
            cache_path="/api/v1/devices/{device_id}/active-session-cache",
            token_file=None,
        ),
        DEVICE_ID,
        lambda: "short-lived-test-token",
        client=http,
    )
    client.heartbeat()
    decision = client.submit_recognition_event({"event_id": str(uuid4())})

    assert requests[0].url.path == f"/api/v1/devices/{DEVICE_ID}/device-heartbeat"
    assert requests[0].headers["X-Device-ID"] == str(DEVICE_ID)
    assert requests[0].headers["Authorization"] == "Bearer short-lived-test-token"
    assert requests[1].url.path == f"/api/v1/devices/{DEVICE_ID}/recognition-events"
    assert requests[1].headers["X-Device-ID"] == str(DEVICE_ID)
    assert decision == {"status": "ok"}
    client.close()
    http.close()


def test_camera_preview_skips_face_detection_without_an_active_viewer(
    tmp_path: Path,
) -> None:
    config = load_config(
        EXAMPLE_CONFIG,
        environ={"PRESENSI_EDGE_DEVICE_ID": str(DEVICE_ID)},
    )

    class FakeCamera:
        def open(self) -> None: ...

        def read(self) -> tuple[bool, object | None]:
            return False, None

        def close(self) -> None: ...

    class FakeApi:
        def close(self) -> None: ...

    class FakeRecognizer:
        def reset(self) -> None: ...

    outbox = EventOutbox(tmp_path / "preview-viewer.sqlite3", max_pending=10)
    service = EdgeService(
        config,
        FakeCamera(),
        FakeApi(),  # type: ignore[arg-type]
        outbox,
        FakeRecognizer(),  # type: ignore[arg-type]
        lambda: {},
    )
    try:
        assert service.preview is not None
        assert service.preview.has_active_viewer() is False

        service._update_camera_diagnostics(object())

        assert service._camera_inspector_attempted is False
    finally:
        outbox.close()


def test_confirmed_attendance_feedback_shows_only_roster_verified_student_name(
    tmp_path: Path,
) -> None:
    config = load_config(
        EXAMPLE_CONFIG,
        environ={"PRESENSI_EDGE_DEVICE_ID": str(DEVICE_ID)},
    )

    class FakeCamera:
        def open(self) -> None: ...

        def read(self) -> tuple[bool, object | None]:
            return False, None

        def close(self) -> None: ...

    class FakeApi:
        def close(self) -> None: ...

    class FakeRecognizer:
        def reset(self) -> None: ...

    outbox = EventOutbox(tmp_path / "preview-feedback.sqlite3", max_pending=10)
    service = EdgeService(
        config,
        FakeCamera(),
        FakeApi(),  # type: ignore[arg-type]
        outbox,
        FakeRecognizer(),  # type: ignore[arg-type]
        lambda: {},
    )
    service._active_session_id = SESSION_ID
    now = datetime.now(UTC)
    service._active_bundle = SessionCacheBundle(
        device_id=DEVICE_ID,
        session_id=SESSION_ID,
        session_status="active",
        generated_at=now,
        session_ends_at=now + timedelta(hours=1),
        expires_at=now + timedelta(minutes=5),
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
        students=(
            CachedStudent(
                student_id=STUDENT_ID,
                student_number="synthetic-001",
                full_name="Synthetic Adult Volunteer",
                templates=(),
            ),
        ),
    )
    try:
        service._update_preview_attendance_result(
            {"session_id": str(SESSION_ID)},
            {
                "decision": "attendance_recorded",
                "attendance": {
                    "status": "present",
                    "student_id": str(STUDENT_ID),
                },
            },
        )

        assert service.preview is not None
        status = service.preview.status()
        assert status["attendance_result"]["decision"] == "recorded"  # type: ignore[index]
        assert status["attendance_result"]["attendance_status"] == "present"  # type: ignore[index]
        assert (
            status["attendance_result"]["display_name"]  # type: ignore[index]
            == "Synthetic Adult Volunteer"
        )
        assert str(STUDENT_ID) not in json.dumps(status["attendance_result"])

        service._active_bundle = None
        service._update_preview_attendance_result(
            {"session_id": str(SESSION_ID)},
            {
                "decision": "attendance_recorded",
                "attendance": {"status": "present", "student_id": str(STUDENT_ID)},
            },
        )
        result_without_roster = service.preview.status()["attendance_result"]
        assert "display_name" not in result_without_roster  # type: ignore[operator]
    finally:
        outbox.close()


def test_core_api_client_renews_device_credential_from_protected_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PRESENSI_EDGE_API_TOKEN", raising=False)
    token_file = tmp_path / "device.token"
    token_file.write_text("old-device-token\n", encoding="utf-8")
    requests: list[httpx.Request] = []
    renewed_expiry = datetime.now(UTC) + timedelta(days=90)

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/device-heartbeat"):
            return httpx.Response(
                200,
                json={
                    "device_id": str(DEVICE_ID),
                    "last_seen_at": datetime.now(UTC).isoformat(),
                    "credential_expires_at": (
                        datetime.now(UTC) + timedelta(days=1)
                    ).isoformat(),
                },
            )
        assert request.url.path.endswith("/credentials/renew")
        return httpx.Response(
            200,
            json={
                "device_id": str(DEVICE_ID),
                "token": "new-device-token",
                "expires_at": renewed_expiry.isoformat(),
            },
        )

    http = httpx.Client(
        base_url="https://api.example.test", transport=httpx.MockTransport(respond)
    )
    client = CoreApiClient(
        ApiSettings(
            base_url="https://api.example.test",
            timeout_seconds=1,
            heartbeat_interval_seconds=5,
            cache_refresh_seconds=3,
            cache_path="/api/v1/devices/{device_id}/active-session-cache",
            token_file=token_file,
        ),
        DEVICE_ID,
        lambda: token_file.read_text(encoding="utf-8").strip(),
        client=http,
    )

    client.heartbeat()

    assert len(requests) == 2
    assert requests[0].headers["Authorization"] == "Bearer old-device-token"
    assert requests[1].url.path == f"/api/v1/devices/{DEVICE_ID}/credentials/renew"
    assert token_file.read_text(encoding="utf-8") == "new-device-token\n"
    client.close()
    http.close()


def test_api_5xx_is_retryable_and_does_not_include_response_body() -> None:
    http = httpx.Client(
        base_url="https://api.example.test",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(503, text="private response detail")
        ),
    )
    client = CoreApiClient(
        ApiSettings(
            base_url="https://api.example.test",
            timeout_seconds=1,
            heartbeat_interval_seconds=5,
            cache_refresh_seconds=3,
            cache_path="/api/v1/devices/{device_id}/active-session-cache",
            token_file=None,
        ),
        DEVICE_ID,
        lambda: "test-token",
        client=http,
    )

    with pytest.raises(ApiCallError) as failure:
        client.heartbeat()

    assert failure.value.retryable is True
    assert failure.value.status_code == 503
    assert "private response detail" not in str(failure.value)
    client.close()
    http.close()


def test_cache_parses_memory_only_gallery_and_keeps_unenrolled_roster() -> None:
    bundle = parse_session_cache(
        sample_bundle_payload(),
        device_id=DEVICE_ID,
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
    )
    cache = ActiveSessionCache()
    cache.replace(bundle)

    assert len(bundle.students) == 2
    assert len(bundle.gallery()) == 1
    assert len(bundle.gallery()[0].embedding.values) == 3
    assert cache.current() == bundle
    assert "1.0" not in repr(bundle)


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("device_id", str(uuid4()), "different device"),
        ("session_status", "closed", "not active"),
        ("generated_at", "not-a-date", "generated_at"),
    ],
)
def test_cache_rejects_invalid_session_scope_and_timestamps(
    key: str, value: str, expected: str
) -> None:
    payload = sample_bundle_payload()
    payload[key] = value

    with pytest.raises(CacheSchemaError, match=expected):
        parse_session_cache(
            payload,
            device_id=DEVICE_ID,
            model_name=MODEL_NAME,
            model_version=MODEL_VERSION,
        )


def test_cache_expiry_is_capped_by_session_end_and_local_offline_policy() -> None:
    now = datetime.now(UTC)
    payload = sample_bundle_payload(now=now)
    session_end = now + timedelta(minutes=2)
    payload["expires_at"] = (now + timedelta(hours=1)).isoformat()
    payload["session_ends_at"] = session_end.isoformat()
    bundle = parse_session_cache(
        payload,
        device_id=DEVICE_ID,
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
        max_offline_seconds=300,
        now=now,
    )
    assert bundle.expires_at == session_end

    cache = ActiveSessionCache()
    cache.replace(bundle)
    assert cache.current(now=session_end) is None

    stale_payload = sample_bundle_payload(now=now - timedelta(minutes=6))
    stale_payload["expires_at"] = (now + timedelta(hours=1)).isoformat()
    stale_payload["session_ends_at"] = (now + timedelta(hours=1)).isoformat()
    with pytest.raises(CacheSchemaError, match="expired"):
        parse_session_cache(
            stale_payload,
            device_id=DEVICE_ID,
            model_name=MODEL_NAME,
            model_version=MODEL_VERSION,
            max_offline_seconds=300,
            now=now,
        )


def test_expired_cache_prevents_service_from_running_another_decision(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    bundle = parse_session_cache(
        sample_bundle_payload(now=now),
        device_id=DEVICE_ID,
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
    )
    expired_bundle = replace(bundle, expires_at=now - timedelta(seconds=1))
    config = EdgeConfig(
        config_path=tmp_path / "edge.yaml",
        device_id=DEVICE_ID,
        api=ApiSettings(
            base_url="https://api.example.test",
            timeout_seconds=1,
            heartbeat_interval_seconds=5,
            cache_refresh_seconds=3,
            cache_path="/api/v1/devices/{device_id}/active-session-cache",
            token_file=None,
        ),
        camera=CameraSettings(0, 1920, 1080, 30, "auto", 4, 1),
        models=ModelSettings(None, None, MODEL_VERSION, None, None),
        quality=QualitySettings(80, 45, 25, 235),
        recognition=RecognitionSettings(None, None, 3, 5, 5, 10, 3),
        liveness=LivenessSettings(False, False, None),
        runtime=RuntimeSettings(tmp_path / "expired.sqlite3", 10, 1, "INFO"),
    )

    class NeverCalledApi:
        def heartbeat(self) -> None: ...

        def submit_recognition_event(self, _payload: dict[str, object]) -> None: ...

    class FakeCamera:
        def open(self) -> None: ...

        def read(self) -> tuple[bool, object | None]:
            return False, None

        def close(self) -> None: ...

    class CountingRecognizer:
        calls = 0

        def process(
            self,
            _frame: object,
            _gallery: tuple[GalleryEntry, ...],
            _captured_at: datetime,
        ) -> TrackDecision:
            self.calls += 1
            raise AssertionError("Expired cache must not reach recognition.")

        def reset(self) -> None: ...

    outbox = EventOutbox(tmp_path / "expired.sqlite3", max_pending=10)
    recognizer = CountingRecognizer()
    service = EdgeService(
        config,
        FakeCamera(),
        NeverCalledApi(),  # type: ignore[arg-type]
        outbox,
        recognizer,  # type: ignore[arg-type]
        lambda: {},
    )
    service.cache.replace(expired_bundle)
    service._active_session_id = bundle.session_id
    service._active_bundle = bundle
    service._gallery = bundle.gallery()

    service._process_frame(object())

    assert recognizer.calls == 0
    assert service.cache.current() is None
    assert service._active_session_id is None
    assert service._gallery == ()
    assert outbox.counts() == (0, 0)
    outbox.close()


def test_outbox_keeps_idempotent_event_payloads_across_retry(tmp_path: Path) -> None:
    outbox = EventOutbox(tmp_path / "events.sqlite3", max_pending=2)
    payload = event_payload(
        TrackDecision(
            track_id="test-camera",
            state="accepted",
            decision=RecognitionDecision(
                outcome="matched",
                student_id=STUDENT_ID,
                confidence=0.95,
                margin=0.4,
            ),
            observation_count=3,
        ),
        device_id=DEVICE_ID,
        session_id=SESSION_ID,
        occurred_at=datetime.now(UTC),
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
        liveness_required=False,
        liveness_enabled=False,
        min_live_score=None,
    )
    event_id = outbox.enqueue(payload)
    assert outbox.enqueue(payload) == event_id
    assert outbox.counts() == (1, 0)
    queued = outbox.due()[0]
    assert queued.event_id == event_id
    assert queued.payload == payload
    assert set(queued.payload) == {
        "event_id",
        "device_id",
        "session_id",
        "student_id",
        "outcome",
        "similarity",
        "confidence",
        "margin",
        "liveness_passed",
        "liveness_score",
        "occurred_at",
        "model_name",
        "model_version",
    }
    outbox.retry(event_id, max_delay_seconds=4, status_code=503)
    assert outbox.due() == []
    due_time = datetime.now(UTC) + timedelta(seconds=5)
    assert outbox.due(now=due_time)[0].attempts == 1
    outbox.acknowledge(event_id)
    assert outbox.counts() == (0, 0)
    outbox.close()


def test_outbox_refuses_biometrics_and_detects_local_id_reuse(tmp_path: Path) -> None:
    outbox = EventOutbox(tmp_path / "events.sqlite3", max_pending=1)
    payload: dict[str, object] = {
        "event_id": str(uuid4()),
        "device_id": str(DEVICE_ID),
        "session_id": str(SESSION_ID),
        "student_id": str(STUDENT_ID),
        "outcome": "matched",
        "similarity": 0.9,
        "confidence": 0.95,
        "margin": 0.2,
        "liveness_passed": None,
        "liveness_score": None,
        "occurred_at": datetime.now(UTC).isoformat(),
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
    }
    outbox.enqueue(payload)
    with pytest.raises(ValueError, match="recognition event contract"):
        outbox.enqueue({**payload, "embedding": [1.0]})
    with pytest.raises(OutboxEventConflict):
        outbox.enqueue({**payload, "confidence": 0.94})
    with pytest.raises(OutboxFullError):
        outbox.enqueue({**payload, "event_id": str(uuid4())})
    outbox.close()


def test_outbox_migrates_prior_sqlite_schema_without_losing_fifo_order(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-events.sqlite3"
    legacy = sqlite3.connect(path)
    legacy.execute(
        """CREATE TABLE edge_event_outbox (
            event_id TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            last_error_status INTEGER,
            created_at TEXT NOT NULL
        )"""
    )
    legacy.execute(
        "CREATE INDEX ix_edge_event_outbox_due "
        "ON edge_event_outbox(status, next_attempt_at, created_at)"
    )
    base_time = datetime.now(UTC)
    expected: list[str] = []
    for index in range(3):
        event_id = str(UUID(int=9000 + index))
        expected.append(event_id)
        payload = {
            "event_id": event_id,
            "device_id": str(DEVICE_ID),
            "session_id": str(SESSION_ID),
            "student_id": str(STUDENT_ID),
            "outcome": "matched",
            "similarity": 0.8,
            "confidence": 0.9,
            "margin": 0.3,
            "liveness_passed": None,
            "liveness_score": None,
            "occurred_at": (base_time + timedelta(seconds=index)).isoformat(),
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
        }
        legacy.execute(
            """INSERT INTO edge_event_outbox
               (event_id, payload_json, attempts, next_attempt_at, status,
                last_error_status, created_at)
               VALUES (?, ?, 0, ?, 'pending', NULL, ?)""",
            (
                event_id,
                json.dumps(payload, sort_keys=True),
                base_time.isoformat(),
                (base_time + timedelta(seconds=index)).isoformat(),
            ),
        )
    legacy.commit()
    legacy.close()

    migrated = EventOutbox(path, max_pending=10)
    assert [str(event.event_id) for event in migrated.due()] == expected
    migrated.close()


class FakeCapture:
    def __init__(self, opened: bool) -> None:
        self.opened = opened
        self.released = False
        self.properties: list[tuple[int, float]] = []

    def isOpened(self) -> bool:
        return self.opened

    def release(self) -> None:
        self.released = True

    def set(self, prop: int, value: float) -> bool:
        self.properties.append((prop, value))
        return True

    def read(self) -> tuple[bool, object]:
        return True, object()


def test_camera_enumeration_and_capture_apply_requested_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captures: list[FakeCapture] = []

    def factory(index: int, _backend: str) -> FakeCapture:
        capture = FakeCapture(opened=index == 1)
        captures.append(capture)
        return capture

    found = camera_module.enumerate_cameras(2, capture_factory=factory)
    assert [camera.index for camera in found] == [1]
    assert all(capture.released for capture in captures)

    fake_cv2 = type(
        "FakeCV2",
        (),
        {
            "CAP_PROP_FRAME_WIDTH": 3,
            "CAP_PROP_FRAME_HEIGHT": 4,
            "CAP_PROP_FPS": 5,
            "CAP_PROP_BUFFERSIZE": 6,
            "VideoCapture": staticmethod(lambda _index: video_capture),
        },
    )()
    video_capture = FakeCapture(opened=True)
    monkeypatch.setattr(camera_module, "_cv2", lambda: fake_cv2)
    camera = camera_module.OpenCVCamera(
        CameraSettings(
            index=0,
            width=1920,
            height=1080,
            fps=30,
            backend="auto",
            scan_max_index=2,
            reconnect_seconds=1,
        )
    )
    camera.open()
    ok, frame = camera.read()
    assert ok and frame is not None
    assert video_capture.properties == [(3, 1920), (4, 1080), (5, 30), (6, 1)]
    camera.close()
    assert video_capture.released


def test_recognizer_keeps_all_template_candidates_for_distinct_student_margin() -> None:
    class FakePipeline:
        max_candidates = 2

        def process(
            self,
            _frame: object,
            _gallery: tuple[GalleryEntry, ...],
            _observation: object,
        ) -> TrackDecision:
            return TrackDecision(
                track_id="test",
                state="collecting",
                decision=RecognitionDecision(outcome="retry"),
                observation_count=0,
            )

    pipeline = FakePipeline()
    recognizer = LocalRecognizer(pipeline, DEVICE_ID)  # type: ignore[arg-type]
    gallery = tuple(
        GalleryEntry(
            student_id=STUDENT_ID if index < 3 else UUID(int=4),
            embedding=FaceEmbedding(
                values=(1.0, float(index + 1)),
                model_name=MODEL_NAME,
                model_version=MODEL_VERSION,
                normalized=True,
            ),
        )
        for index in range(5)
    )

    recognizer.process(object(), gallery, datetime.now(UTC))

    assert pipeline.max_candidates == 5


def test_transient_api_failures_leave_edge_service_and_outbox_usable(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = EdgeConfig(
        config_path=tmp_path / "config.yaml",
        device_id=DEVICE_ID,
        api=ApiSettings(
            base_url="https://api.example.test",
            timeout_seconds=1,
            heartbeat_interval_seconds=5,
            cache_refresh_seconds=3,
            cache_path="/api/v1/devices/{device_id}/active-session-cache",
            token_file=None,
        ),
        camera=CameraSettings(0, 1920, 1080, 30, "auto", 4, 1),
        models=ModelSettings(None, None, MODEL_VERSION, None, None),
        quality=QualitySettings(80, 45, 25, 235),
        recognition=RecognitionSettings(None, None, 3, 5, 5, 10, 3),
        liveness=LivenessSettings(False, False, None),
        runtime=RuntimeSettings(tmp_path / "outbox.sqlite3", 10, 8, "INFO"),
    )

    class FakeApi:
        def heartbeat(self) -> None:
            raise ApiCallError(503, retryable=True)

        def submit_recognition_event(self, _payload: dict[str, object]) -> None:
            raise ApiCallError(503, retryable=True)

    class FakeCamera:
        def open(self) -> None: ...

        def read(self) -> tuple[bool, object | None]:
            return False, None

        def close(self) -> None: ...

    class FakeRecognizer:
        def process(self, _frame, _gallery, _captured_at) -> TrackDecision:
            raise AssertionError("No camera frame should be processed in this test.")

        def reset(self) -> None: ...

    outbox = EventOutbox(tmp_path / "outbox.sqlite3", max_pending=10)
    payload = {
        "event_id": str(uuid4()),
        "device_id": str(DEVICE_ID),
        "session_id": str(SESSION_ID),
        "student_id": str(STUDENT_ID),
        "outcome": "matched",
        "similarity": 0.8,
        "confidence": 0.9,
        "margin": 0.3,
        "liveness_passed": None,
        "liveness_score": None,
        "occurred_at": datetime.now(UTC).isoformat(),
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
    }
    event_id = outbox.enqueue(payload)
    service = EdgeService(
        config,
        FakeCamera(),
        FakeApi(),  # type: ignore[arg-type]
        outbox,
        FakeRecognizer(),  # type: ignore[arg-type]
        lambda: (_ for _ in ()).throw(ApiCallError(503, retryable=True)),
    )

    with caplog.at_level(logging.WARNING):
        service._send_heartbeat()
        service._refresh_cache()
        service._flush_outbox()

    assert service.status()["session_cache_loaded"] is False
    assert service.status()["pending_events"] == 1
    assert (
        outbox.due(now=datetime.now(UTC) + timedelta(seconds=5))[0].event_id == event_id
    )
    serialized_logs = JsonLogFormatter().format(caplog.records[-1])
    assert "embedding" not in serialized_logs.lower()
    assert "short-lived-test-token" not in serialized_logs
    outbox.close()


def test_ten_offline_events_survive_restart_and_reconnect_in_fifo_idempotently(
    tmp_path: Path,
) -> None:
    second_student_id = UUID("33000000-0000-4000-8000-000000000004")
    config = EdgeConfig(
        config_path=tmp_path / "edge.yaml",
        device_id=DEVICE_ID,
        api=ApiSettings(
            base_url="https://api.example.test",
            timeout_seconds=1,
            heartbeat_interval_seconds=5,
            cache_refresh_seconds=3,
            cache_path="/api/v1/devices/{device_id}/active-session-cache",
            token_file=None,
        ),
        camera=CameraSettings(0, 1920, 1080, 30, "auto", 4, 1),
        models=ModelSettings(None, None, MODEL_VERSION, None, None),
        quality=QualitySettings(80, 45, 25, 235),
        # Synthetic calibrated values let this offline-queue test exercise the
        # mocked decision path. Production values still come from calibration.
        recognition=RecognitionSettings(0.5, 0.1, 3, 5, 5, 10, 3),
        liveness=LivenessSettings(False, False, None),
        runtime=RuntimeSettings(tmp_path / "queue.sqlite3", 20, 0.5, "INFO"),
    )

    class IdempotentFakeApi:
        available = False
        lose_response_for: str | None = None

        def __init__(self) -> None:
            self.attempted: list[str] = []
            self.accepted: list[str] = []
            self._accepted_ids: set[str] = set()

        def heartbeat(self) -> None:
            if not self.available:
                raise ApiCallError(503, retryable=True)

        def submit_recognition_event(self, payload: dict[str, object]) -> None:
            event_id = str(payload["event_id"])
            self.attempted.append(event_id)
            if not self.available:
                raise ApiCallError(503, retryable=True)
            if event_id not in self._accepted_ids:
                self._accepted_ids.add(event_id)
                self.accepted.append(event_id)
            if self.lose_response_for == event_id:
                self.lose_response_for = None
                raise ApiCallError(None, retryable=True)

    class FakeCamera:
        def open(self) -> None: ...

        def read(self) -> tuple[bool, object | None]:
            return False, None

        def close(self) -> None: ...

    class FakeRecognizer:
        def __init__(self) -> None:
            self.candidate_ids = [STUDENT_ID, second_student_id] * 5
            self.processed = 0
            self.reset_count = 0

        def process(
            self,
            _frame: object,
            gallery: tuple[GalleryEntry, ...],
            _captured_at: datetime,
        ) -> TrackDecision:
            assert len(gallery) == 2
            candidate = self.candidate_ids[self.processed]
            self.processed += 1
            return TrackDecision(
                track_id="offline-test-camera",
                state="accepted",
                decision=RecognitionDecision(
                    outcome="matched",
                    student_id=candidate,
                    confidence=0.95,
                    margin=0.4,
                ),
                observation_count=3,
            )

        def reset(self) -> None:
            self.reset_count += 1

    cache_payload = sample_bundle_payload()
    roster = cache_payload["roster"]
    assert isinstance(roster, list)
    second_student = roster[1]
    first_student = roster[0]
    assert isinstance(second_student, dict) and isinstance(first_student, dict)
    second_student["templates"] = first_student["templates"]
    bundle = parse_session_cache(
        cache_payload,
        device_id=DEVICE_ID,
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
    )

    api = IdempotentFakeApi()
    outbox = EventOutbox(config.runtime.outbox_path, max_pending=20)
    recognizer = FakeRecognizer()
    first_process = EdgeService(
        config,
        FakeCamera(),
        api,  # type: ignore[arg-type]
        outbox,
        recognizer,  # type: ignore[arg-type]
        lambda: {},
    )
    first_process.cache.replace(bundle)
    for _ in range(10):
        first_process._process_frame(object())
    assert recognizer.processed == 10
    assert first_process.preview is not None
    assert first_process.preview._status["recognition_state"] == "accepted"
    assert first_process.preview._status["display_name"] == "Not Enrolled"
    assert outbox.counts() == (10, 0)

    # The API is unavailable while decisions keep being queued locally.
    first_process._flush_outbox()
    expected_order = [
        str(event.event_id)
        for event in outbox.due(now=datetime.now(UTC) + timedelta(minutes=1))
    ]
    assert len(expected_order) == 10
    assert api.attempted == [expected_order[0]]
    assert outbox.due(now=datetime.now(UTC) + timedelta(milliseconds=100)) == []
    outbox.close()

    # A new process opens the same SQLite file and resumes the pending queue.
    reopened_outbox = EventOutbox(config.runtime.outbox_path, max_pending=20)
    assert reopened_outbox.counts() == (10, 0)
    restarted_process = EdgeService(
        config,
        FakeCamera(),
        api,  # type: ignore[arg-type]
        reopened_outbox,
        FakeRecognizer(),  # type: ignore[arg-type]
        lambda: {},
    )
    time.sleep(0.55)
    api.available = True
    api.lose_response_for = expected_order[0]
    restarted_process._flush_outbox()
    assert api.accepted == [expected_order[0]]
    assert (
        reopened_outbox.due(now=datetime.now(UTC) + timedelta(milliseconds=100)) == []
    )

    # The simulated server already committed the first UUID before its response
    # was lost. Replaying that UUID is idempotent, then later UUIDs drain FIFO.
    time.sleep(0.55)
    restarted_process._flush_outbox()
    restarted_process._flush_outbox()
    assert api.accepted == expected_order
    assert len(set(api.accepted)) == 10
    assert api.attempted.count(expected_order[0]) == 3
    assert reopened_outbox.counts() == (0, 0)
    reopened_outbox.close()
