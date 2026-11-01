from __future__ import annotations

import base64
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from presensi_edge_agent import camera as camera_module
from presensi_edge_agent.api import ApiCallError, CoreApiClient
from presensi_edge_agent.camera import CameraUnavailableError, OpenCVCamera
from presensi_edge_agent.central_ai import (
    BurstFrame,
    CentralAIClient,
    CentralDecision,
)
from presensi_edge_agent.config import (
    ApiSettings,
    CentralAISettings,
    EdgeConfigError,
    load_config,
)
from presensi_edge_agent.gateway import (
    FrameAssessment,
    StbGatewayService,
    _event_payload,
)
from presensi_edge_agent.outbox import EventOutbox

ROOT = Path(__file__).resolve().parents[3]
GATEWAY_CONFIG = ROOT / "apps" / "edge-agent" / "config" / "stb-gateway.example.yaml"
DEVICE_ID = UUID("44000000-0000-4000-8000-000000000001")
SESSION_ID = UUID("44000000-0000-4000-8000-000000000002")
STUDENT_ID = UUID("44000000-0000-4000-8000-000000000003")


def gateway_config(tmp_path: Path):
    now = datetime.now(UTC)
    return load_config(
        GATEWAY_CONFIG,
        environ={
            "PRESENSI_EDGE_DEVICE_ID": str(DEVICE_ID),
            "PRESENSI_EDGE_SESSION_ID": str(SESSION_ID),
            "PRESENSI_EDGE_SESSION_STARTS_AT": (now - timedelta(minutes=5)).isoformat(),
            "PRESENSI_EDGE_SESSION_ENDS_AT": (now + timedelta(minutes=55)).isoformat(),
        },
    )


def test_stb_profile_needs_no_local_recognition_models(tmp_path: Path) -> None:
    config = gateway_config(tmp_path)

    assert config.mode == "STB_GATEWAY"
    assert config.camera.width == 640
    assert config.camera.height == 360
    assert config.camera.fps == 10
    assert config.models.yunet_path is None
    assert config.models.sface_path is None
    config.require_runtime(api_token="core-token", ai_token="device-token")


def test_stb_profile_rejects_full_hd_and_stops_at_expired_pinned_window(
    tmp_path: Path,
) -> None:
    config = gateway_config(tmp_path)
    too_large = replace(config, camera=replace(config.camera, width=1920, height=1080))
    with pytest.raises(EdgeConfigError, match="1280x720"):
        too_large.require_runtime(api_token="core-token", ai_token="device-token")

    expired = replace(
        config,
        gateway=replace(
            config.gateway,
            session_ends_at=datetime.now(UTC) - timedelta(seconds=1),
        ),
    )
    expired.require_runtime(api_token="core-token", ai_token="device-token")
    outbox = EventOutbox(tmp_path / "expired-window.sqlite3", max_pending=10)
    service = StbGatewayService(
        expired,
        object(),
        object(),
        object(),
        outbox,
        object(),
    )  # type: ignore[arg-type]
    assert not service._session_active()
    outbox.close()


def test_gateway_camera_rejects_driver_mode_above_configured_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = gateway_config(tmp_path)

    class Capture:
        released = False

        def isOpened(self) -> bool:
            return True

        def set(self, _property: int, _value: float) -> bool:
            return True

        def get(self, property_id: int) -> int:
            return 1920 if property_id == 3 else 1080

        def release(self) -> None:
            self.released = True

    capture = Capture()
    fake_cv2 = type(
        "FakeCV2",
        (),
        {
            "CAP_PROP_FRAME_WIDTH": 3,
            "CAP_PROP_FRAME_HEIGHT": 4,
            "CAP_PROP_FPS": 5,
            "CAP_PROP_BUFFERSIZE": 6,
            "CAP_V4L2": 7,
            "VideoCapture": staticmethod(lambda *_args: capture),
        },
    )()
    monkeypatch.setattr(camera_module, "_cv2", lambda: fake_cv2)
    camera = OpenCVCamera(
        config.camera,
        max_frame_size=(config.camera.width, config.camera.height),
    )

    with pytest.raises(CameraUnavailableError, match="negotiated"):
        camera.open()
    assert capture.released


def test_central_ai_client_sends_ordered_jpeg_burst_and_validates_response() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "session_id": str(SESSION_ID),
                "track_id": "camera-0",
                "status": "accepted",
                "outcome": "matched",
                "candidate": {
                    "student_id": str(STUDENT_ID),
                    "confidence": 0.94,
                    "margin": 1.15,
                },
                "reason_code": None,
                "liveness_score": 0.88,
                "observations": 3,
                "frames_processed": 3,
                "model_name": "opencv-zoo-sface",
                "model_version": "calibrated-central-model-v1",
            },
        )

    transport = httpx.MockTransport(respond)
    client = httpx.Client(
        base_url="https://ai.example.test", transport=transport, timeout=1
    )
    ai = CentralAIClient(
        CentralAISettings("https://ai.example.test", None, 1),
        DEVICE_ID,
        lambda: "per-device-secret-token",
        client=client,
    )
    now = datetime.now(UTC)
    decision = ai.recognize_burst(
        session_id=SESSION_ID,
        track_id="camera-0",
        frames=[
            BurstFrame(b"jpeg-one", now),
            BurstFrame(b"jpeg-two", now + timedelta(milliseconds=200)),
        ],
    )

    request = seen[0]
    payload = request.read()
    parsed = __import__("json").loads(payload)
    assert request.url.path == f"/api/v1/recognition/sessions/{SESSION_ID}/bursts"
    assert request.headers["X-Device-ID"] == str(DEVICE_ID)
    assert request.headers["Authorization"] == "Bearer per-device-secret-token"
    assert parsed["track_id"] == "camera-0"
    assert [base64.b64decode(frame["image_base64"]) for frame in parsed["frames"]] == [
        b"jpeg-one",
        b"jpeg-two",
    ]
    assert decision.student_id == STUDENT_ID
    assert decision.margin == 1.15
    assert b"embedding" not in payload
    ai.close()
    client.close()


def test_central_ai_rejects_wrong_track_and_oversized_jpeg() -> None:
    client = httpx.Client(
        base_url="https://ai.example.test",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "session_id": str(SESSION_ID),
                    "track_id": "other-track",
                    "outcome": "no_match",
                    "candidate": None,
                    "reason_code": None,
                    "liveness_score": None,
                    "model_name": "opencv-zoo-sface",
                    "model_version": "model-v1",
                },
            )
        ),
    )
    ai = CentralAIClient(
        CentralAISettings("https://ai.example.test", None, 1),
        DEVICE_ID,
        lambda: "device-token",
        client=client,
    )
    now = datetime.now(UTC)
    with pytest.raises(ApiCallError) as mismatch:
        ai.recognize_burst(
            session_id=SESSION_ID,
            track_id="camera-0",
            frames=[BurstFrame(b"jpeg", now)],
        )
    assert mismatch.value.retryable is False
    with pytest.raises(ValueError, match="frame exceeds"):
        ai.recognize_burst(
            session_id=SESSION_ID,
            track_id="camera-0",
            frames=[BurstFrame(b"x" * (1_048_576 + 1), now)],
        )
    ai.close()
    client.close()


def test_central_ai_timeout_is_retryable_and_does_not_expose_token() -> None:
    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("internal timeout detail")

    client = httpx.Client(
        base_url="https://ai.example.test", transport=httpx.MockTransport(timeout)
    )
    ai = CentralAIClient(
        CentralAISettings("https://ai.example.test", None, 1),
        DEVICE_ID,
        lambda: "private-device-token",
        client=client,
    )
    with pytest.raises(ApiCallError) as failure:
        ai.recognize_burst(
            session_id=SESSION_ID,
            track_id="camera-0",
            frames=[BurstFrame(b"jpeg", datetime.now(UTC))],
        )
    assert failure.value.retryable
    assert "private-device-token" not in str(failure.value)
    assert "internal timeout detail" not in str(failure.value)
    ai.close()
    client.close()


@pytest.mark.parametrize("status_code", [401, 403, 422])
def test_central_ai_credential_and_client_errors_are_not_retryable(
    status_code: int,
) -> None:
    """Align with CoreApiClient: 4xx (except 408/425/429) must dead-letter.

    Retrying a rejected credential with the same token loops forever and
    stalls the FIFO outbox behind the backed-off head event.
    """

    def rejected(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="credential rejected")

    client = httpx.Client(
        base_url="https://ai.example.test", transport=httpx.MockTransport(rejected)
    )
    ai = CentralAIClient(
        CentralAISettings("https://ai.example.test", None, 1),
        DEVICE_ID,
        lambda: "device-token",
        client=client,
    )
    with pytest.raises(ApiCallError) as failure:
        ai.recognize_burst(
            session_id=SESSION_ID,
            track_id="camera-0",
            frames=[BurstFrame(b"jpeg", datetime.now(UTC))],
        )
    assert failure.value.status_code == status_code
    assert failure.value.retryable is False
    ai.close()
    client.close()


@pytest.mark.parametrize("status_code", [408, 429, 503])
def test_central_ai_transient_errors_stay_retryable(status_code: int) -> None:
    def transient(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="try again")

    client = httpx.Client(
        base_url="https://ai.example.test", transport=httpx.MockTransport(transient)
    )
    ai = CentralAIClient(
        CentralAISettings("https://ai.example.test", None, 1),
        DEVICE_ID,
        lambda: "device-token",
        client=client,
    )
    with pytest.raises(ApiCallError) as failure:
        ai.recognize_burst(
            session_id=SESSION_ID,
            track_id="camera-0",
            frames=[BurstFrame(b"jpeg", datetime.now(UTC))],
        )
    assert failure.value.retryable is True
    ai.close()
    client.close()


def test_gallery_fetch_sends_known_version_and_reports_not_modified() -> None:
    seen_paths: list[str] = []

    def conditional(_request: httpx.Request) -> httpx.Response:
        seen_paths.append(str(_request.url))
        if "known_generated_at=" in str(_request.url):
            return httpx.Response(304)
        return httpx.Response(200, json={"generated_at": "2026-01-01T00:00:00+00:00"})

    from presensi_edge_agent.api import GalleryNotModified

    client = httpx.Client(
        base_url="https://api.example.test", transport=httpx.MockTransport(conditional)
    )
    api = CoreApiClient(
        ApiSettings(
            base_url="https://api.example.test",
            timeout_seconds=1,
            heartbeat_interval_seconds=5,
            cache_refresh_seconds=3,
            cache_path="/api/v1/devices/{device_id}/active-session-cache",
            token_file=None,
        ),
        DEVICE_ID,
        lambda: "device-token",
        client=client,
    )
    payload = api.fetch_active_session_cache()
    assert payload["generated_at"] == "2026-01-01T00:00:00+00:00"
    assert "known_generated_at=" not in seen_paths[0]

    api.set_gallery_version_provider(lambda: "2026-01-01T00:00:00+00:00")
    with pytest.raises(GalleryNotModified):
        api.fetch_active_session_cache()
    assert "known_generated_at=2026-01-01T00%3A00%3A00%2B00%3A00" in seen_paths[1]
    api.close()
    client.close()


def test_gateway_skips_malformed_burst_without_camera_reconnect(
    tmp_path: Path,
) -> None:
    """A ValueError from burst recognition is a data problem, not a camera
    failure: the burst is skipped and the capture loop keeps running."""
    config = gateway_config(tmp_path)

    class Camera:
        def open(self) -> None: ...

        def read(self) -> tuple[bool, object | None]:
            return True, object()

        def close(self) -> None: ...

    class Api:
        def heartbeat(self) -> None: ...

        def submit_recognition_event(self, _payload: dict[str, object]) -> None: ...

    class BrokenAI:
        def recognize_burst(self, **_kwargs: object) -> CentralDecision:
            raise ValueError("Captured frame timestamps must be strictly ordered.")

        def close(self) -> None: ...

    class Processor:
        def assess(self, _frame: object) -> FrameAssessment:
            return FrameAssessment(8, 120, 12)

        def encode_jpeg(self, _frame: object, _quality: int) -> bytes:
            return b"jpeg"

    outbox = EventOutbox(tmp_path / "skipped-burst.sqlite3", max_pending=10)
    service = StbGatewayService(
        config,
        Camera(),
        Api(),
        BrokenAI(),
        outbox,
        Processor(),  # type: ignore[arg-type]
    )
    assert service.session_id == SESSION_ID
    service._submit_burst([BurstFrame(b"jpeg", datetime.now(UTC))])
    assert outbox.counts() == (0, 0)
    outbox.close()


def test_ai_decision_is_converted_to_core_event_without_frame_data() -> None:
    occurred_at = datetime.now(UTC)
    decision = CentralDecision(
        session_id=SESSION_ID,
        track_id="camera-0",
        outcome="matched",
        student_id=STUDENT_ID,
        confidence=0.9,
        margin=1.2,
        reason_code=None,
        liveness_score=0.8,
        model_name="opencv-zoo-sface",
        model_version="central-v3",
    )
    payload = _event_payload(decision, device_id=DEVICE_ID, occurred_at=occurred_at)

    assert payload["device_id"] == str(DEVICE_ID)
    assert payload["session_id"] == str(SESSION_ID)
    assert payload["student_id"] == str(STUDENT_ID)
    assert payload["confidence"] == 0.9
    assert payload["similarity"] is None
    # Central allows margin up to 2.0 (raw gap); API stores [0, 1] — clamp.
    assert payload["margin"] == 1.0
    assert payload["liveness_passed"] is True
    assert payload["occurred_at"] == occurred_at.isoformat()
    assert set(payload) == {
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


def test_gateway_filters_low_quality_and_bursts_only_qualified_frames(
    tmp_path: Path,
) -> None:
    config = gateway_config(tmp_path)

    class Camera:
        frames = [object(), object(), object()]

        def read(self) -> tuple[bool, object | None]:
            return True, self.frames.pop(0)

        def open(self) -> None: ...

        def close(self) -> None: ...

    class Api:
        def heartbeat(self) -> None: ...

        def submit_recognition_event(self, _payload: dict[str, object]) -> None: ...

    class AI:
        def close(self) -> None: ...

    class Processor:
        assessments = [
            FrameAssessment(8, 120, 12),
            FrameAssessment(9, 120, 1),
            FrameAssessment(7, 120, 12),
        ]

        def assess(self, _frame: object) -> FrameAssessment:
            return self.assessments.pop(0)

        def encode_jpeg(self, frame: object, _quality: int) -> bytes:
            return b"good-frame" if frame is not None else b""

    outbox = EventOutbox(tmp_path / "gateway.sqlite3", max_pending=10)
    service = StbGatewayService(
        config,
        Camera(),
        Api(),
        AI(),
        outbox,
        Processor(),  # type: ignore[arg-type]
    )
    first = object()
    first_assessment = FrameAssessment(8, 120, 12)
    frames = service._capture_burst(first, first_assessment)

    assert len(frames) == 2
    assert all(frame.image == b"good-frame" for frame in frames)
    outbox.close()


def test_capture_burst_aborts_and_drops_submit_while_stopping(
    tmp_path: Path,
) -> None:
    """Shutdown during a burst must not keep reading the camera or enqueue.

    The interval wait wakes early on stop; the burst must break instead of
    grabbing another frame, and the submit path must drop the partial burst
    because the outbox is about to close.
    """
    config = gateway_config(tmp_path)

    class Camera:
        reads = 0

        def read(self) -> tuple[bool, object | None]:
            type(self).reads += 1
            return True, object()

        def open(self) -> None: ...

        def close(self) -> None: ...

    class Api:
        def heartbeat(self) -> None: ...

        def submit_recognition_event(self, _payload: dict[str, object]) -> None: ...

    class AI:
        def recognize_burst(self, **_kwargs: object) -> CentralDecision:
            raise AssertionError("must not reach AI while stopping")

        def close(self) -> None: ...

    class Processor:
        def assess(self, _frame: object) -> FrameAssessment:
            return FrameAssessment(8, 120, 12)

        def encode_jpeg(self, _frame: object, _quality: int) -> bytes:
            return b"jpeg"

    outbox = EventOutbox(tmp_path / "stopping-burst.sqlite3", max_pending=10)
    service = StbGatewayService(
        config,
        Camera(),
        Api(),
        AI(),
        outbox,
        Processor(),  # type: ignore[arg-type]
    )
    service.stop_event.set()
    frames = service._capture_burst(object(), FrameAssessment(8, 120, 12))
    assert frames == []
    assert Camera.reads == 0
    service._submit_burst([BurstFrame(b"jpeg", datetime.now(UTC))])
    assert outbox.counts() == (0, 0)
    outbox.close()


def test_gateway_outbox_retries_after_core_api_reconnect(tmp_path: Path) -> None:
    config = gateway_config(tmp_path)
    config = replace(config, api=replace(config.api, heartbeat_interval_seconds=0.1))

    class Camera:
        def open(self) -> None: ...

        def read(self) -> tuple[bool, object | None]:
            return False, None

        def close(self) -> None: ...

    class RecoveringApi:
        reachable = False
        delivered: list[str]

        def __init__(self) -> None:
            self.delivered = []
            self.heartbeats = 0

        def heartbeat(self) -> None:
            self.heartbeats += 1
            if not self.reachable:
                raise ApiCallError(503, retryable=True)

        def submit_recognition_event(self, payload: dict[str, object]) -> None:
            if not self.reachable:
                raise ApiCallError(503, retryable=True)
            self.delivered.append(str(payload["event_id"]))

    class AI:
        def close(self) -> None: ...

    class Processor:
        def assess(self, _frame: object) -> FrameAssessment:
            return FrameAssessment(0, 120, 12)

        def encode_jpeg(self, _frame: object, _quality: int) -> bytes:
            return b"jpeg"

    outbox = EventOutbox(tmp_path / "reconnect.sqlite3", max_pending=10)
    occurred_at = datetime.now(UTC)
    outbox.enqueue(
        _event_payload(
            CentralDecision(
                session_id=SESSION_ID,
                track_id="camera-0",
                outcome="matched",
                student_id=STUDENT_ID,
                confidence=0.9,
                margin=0.5,
                reason_code=None,
                liveness_score=None,
                model_name="opencv-zoo-sface",
                model_version="central-v1",
            ),
            device_id=DEVICE_ID,
            occurred_at=occurred_at,
        )
    )
    api = RecoveringApi()
    service = StbGatewayService(config, Camera(), api, AI(), outbox, Processor())  # type: ignore[arg-type]
    worker = threading.Thread(target=service._sync_worker, daemon=True)
    worker.start()
    time.sleep(1.1)
    api.reachable = True
    deadline = time.monotonic() + 3
    while not api.delivered and time.monotonic() < deadline:
        time.sleep(0.05)
    service.stop()
    worker.join(timeout=1)

    assert api.heartbeats >= 2
    assert len(api.delivered) == 1
    assert outbox.counts() == (0, 0)
    outbox.close()


def test_gateway_discovers_session_and_caps_offline_use(tmp_path: Path) -> None:
    config = gateway_config(tmp_path)
    config = replace(config, api=replace(config.api, cache_max_offline_seconds=30))
    now = datetime.now(UTC)

    class Api:
        def discover_active_sessions(self) -> list[dict[str, object]]:
            return [
                {
                    "session_id": str(SESSION_ID),
                    "session_status": "active",
                    "session_ends_at": (now + timedelta(hours=2)).isoformat(),
                    "expires_at": (now + timedelta(hours=1)).isoformat(),
                }
            ]

    class Camera:
        def open(self) -> None: ...

        def read(self) -> tuple[bool, object | None]:
            return False, None

        def close(self) -> None: ...

    class AI:
        def close(self) -> None: ...

    class Processor:
        def assess(self, _frame: object) -> FrameAssessment:
            return FrameAssessment(0, 120, 12)

        def encode_jpeg(self, _frame: object, _quality: int) -> bytes:
            return b"jpeg"

    outbox = EventOutbox(tmp_path / "discovery.sqlite3", max_pending=10)
    service = StbGatewayService(
        config,
        Camera(),
        Api(),
        AI(),
        outbox,
        Processor(),  # type: ignore[arg-type]
    )
    service._refresh_active_session()

    assert service.session_id == SESSION_ID
    assert service._active_session_expires_at is not None
    assert service._active_session_expires_at <= datetime.now(UTC) + timedelta(
        seconds=31
    )
    assert service._session_active()
    service._active_session_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert not service._session_active()
    outbox.close()


def test_central_ai_response_requires_and_returns_model_name() -> None:
    from presensi_edge_agent.central_ai import _parse_decision as _parse_burst_response

    base: dict[str, object] = {
        "session_id": str(SESSION_ID),
        "track_id": "camera-0",
        "outcome": "no_match",
        "candidate": None,
        "reason_code": "below_threshold",
        "liveness_score": None,
        "model_version": "central-v9",
    }
    missing = dict(base)
    with pytest.raises(ValueError, match="model name"):
        _parse_burst_response(
            missing, requested_session=SESSION_ID, requested_track="camera-0"
        )
    parsed = _parse_burst_response(
        {**base, "model_name": "custom-calibrated-model"},
        requested_session=SESSION_ID,
        requested_track="camera-0",
    )
    assert parsed.model_name == "custom-calibrated-model"
    assert parsed.model_version == "central-v9"


def test_gateway_event_payload_uses_central_model_name_not_hardcoded() -> None:
    occurred_at = datetime.now(UTC)
    decision = CentralDecision(
        session_id=SESSION_ID,
        track_id="camera-0",
        outcome="matched",
        student_id=STUDENT_ID,
        confidence=0.9,
        margin=0.5,
        reason_code=None,
        liveness_score=None,
        model_name="custom-calibrated-model",
        model_version="central-v9",
    )
    payload = _event_payload(decision, device_id=DEVICE_ID, occurred_at=occurred_at)
    assert payload["model_name"] == "custom-calibrated-model"
    assert payload["model_version"] == "central-v9"


def test_gateway_margin_clamped_to_api_range() -> None:
    occurred_at = datetime.now(UTC)

    def payload_with(margin: float | None) -> dict[str, object]:
        return _event_payload(
            CentralDecision(
                session_id=SESSION_ID,
                track_id="camera-0",
                outcome="matched",
                student_id=STUDENT_ID,
                confidence=0.9,
                margin=margin,
                reason_code=None,
                liveness_score=None,
                model_name="opencv-zoo-sface",
                model_version="central-v1",
            ),
            device_id=DEVICE_ID,
            occurred_at=occurred_at,
        )

    assert payload_with(1.2)["margin"] == 1.0
    assert payload_with(2.0)["margin"] == 1.0
    assert payload_with(0.5)["margin"] == 0.5
    assert payload_with(None)["margin"] is None


def test_gateway_sync_worker_survives_unexpected_error(tmp_path: Path) -> None:
    config = gateway_config(tmp_path)
    config = replace(config, api=replace(config.api, heartbeat_interval_seconds=10))

    class Camera:
        def open(self) -> None: ...

        def read(self) -> tuple[bool, object | None]:
            return False, None

        def close(self) -> None: ...

    class FlakyApi:
        def __init__(self) -> None:
            self.heartbeats = 0
            self.failed_once = False

        def heartbeat(self) -> None:
            self.heartbeats += 1
            if not self.failed_once:
                self.failed_once = True
                raise RuntimeError("boom")

    class AI:
        def close(self) -> None: ...

    class Processor:
        def assess(self, _frame: object) -> FrameAssessment:
            return FrameAssessment(0, 120, 12)

        def encode_jpeg(self, _frame: object, _quality: int) -> bytes:
            return b"jpeg"

    outbox = EventOutbox(tmp_path / "flaky-sync.sqlite3", max_pending=10)
    api = FlakyApi()
    service = StbGatewayService(config, Camera(), api, AI(), outbox, Processor())  # type: ignore[arg-type]
    worker = threading.Thread(target=service._sync_worker, daemon=True)
    worker.start()
    time.sleep(1.6)
    service.stop()
    worker.join(timeout=2)
    assert api.heartbeats >= 1
    assert worker.is_alive() is False
    outbox.close()
