from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from presensi_edge_agent.api import ApiCallError, CoreApiClient
from presensi_edge_agent.camera import CameraUnavailableError
from presensi_edge_agent.central_ai import BurstFrame, CentralDecision
from presensi_edge_agent.config import EdgeConfig, resolve_ai_token, resolve_api_token
from presensi_edge_agent.logging import log_event
from presensi_edge_agent.outbox import EventOutbox, OutboxFullError

logger = logging.getLogger("presensi_edge_agent")


class CameraSource(Protocol):
    def open(self) -> None: ...

    def read(self) -> tuple[bool, object | None]: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class FrameAssessment:
    motion_score: float
    brightness: float
    sharpness: float


class FrameProcessor(Protocol):
    def assess(self, frame: object) -> FrameAssessment: ...

    def encode_jpeg(self, frame: object, quality: int) -> bytes: ...


class CentralRecognizer(Protocol):
    def recognize_burst(
        self,
        *,
        session_id: UUID,
        track_id: str,
        frames: list[BurstFrame],
    ) -> CentralDecision: ...

    def close(self) -> None: ...


class OpenCVFrameProcessor:
    """Tiny downsampled motion and quality gate; it loads no face model."""

    def __init__(self) -> None:
        import importlib

        try:
            self.cv2: Any = importlib.import_module("cv2")
        except ImportError as exc:
            raise CameraUnavailableError(
                "Install the edge camera extra for STB_GATEWAY capture."
            ) from exc
        self._previous: Any | None = None

    def _small_gray(self, frame: object) -> Any:
        resized = self.cv2.resize(frame, (160, 90), interpolation=self.cv2.INTER_AREA)
        return self.cv2.cvtColor(resized, self.cv2.COLOR_BGR2GRAY)

    def assess(self, frame: object) -> FrameAssessment:
        import numpy as np

        gray = self._small_gray(frame)
        previous = self._previous
        self._previous = gray
        motion = (
            float(np.mean(self.cv2.absdiff(gray, previous)))
            if previous is not None
            else 0.0
        )
        sharpness = float(self.cv2.Laplacian(gray, self.cv2.CV_64F).var())
        brightness = float(np.mean(gray))
        return FrameAssessment(motion, brightness, sharpness)

    def encode_jpeg(self, frame: object, quality: int) -> bytes:
        ok, encoded = self.cv2.imencode(
            ".jpg", frame, [int(self.cv2.IMWRITE_JPEG_QUALITY), quality]
        )
        if not ok:
            raise ValueError("OpenCV could not encode the camera frame.")
        return bytes(encoded)


class StbGatewayService:
    """Low-cost UVC sampler that sends bounded bursts to central inference."""

    def __init__(
        self,
        config: EdgeConfig,
        camera: CameraSource,
        api: CoreApiClient,
        ai: CentralRecognizer,
        outbox: EventOutbox,
        processor: FrameProcessor,
    ) -> None:
        if config.device_id is None or config.gateway.session_id is None:
            raise ValueError("STB gateway device and session IDs are required.")
        self.config = config
        self.device_id = config.device_id
        self.session_id = config.gateway.session_id
        self.camera = camera
        self.api = api
        self.ai = ai
        self.outbox = outbox
        self.processor = processor
        self.stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._camera_open = False
        self._last_burst_at = 0.0
        self._last_periodic_at = 0.0

    def status(self) -> dict[str, object]:
        pending, dead_letter = self.outbox.counts()
        return {
            "service": "presensi-edge-agent",
            "profile": "STB_GATEWAY",
            "camera_open": self._camera_open,
            "device_id_configured": self.config.device_id is not None,
            "active_session_id": str(self.session_id),
            "session_ends_at": self.config.gateway.session_ends_at.isoformat()
            if self.config.gateway.session_ends_at
            else None,
            "pending_events": pending,
            "dead_letter_events": dead_letter,
            "local_face_model_loaded": False,
        }

    def run(self) -> None:
        self.config.require_runtime(
            api_token=resolve_api_token(self.config),
            ai_token=resolve_ai_token(self.config),
        )
        settings = self.config.gateway
        log_event(
            logger,
            logging.INFO,
            "edge_agent_starting",
            profile="STB_GATEWAY",
            camera_index=self.config.camera.index,
            capture_width=self.config.camera.width,
            capture_height=self.config.camera.height,
            requested_camera_fps=self.config.camera.fps,
            frame_burst_count=settings.burst_frame_count,
            periodic_burst_seconds=settings.periodic_burst_seconds,
            local_face_model_loaded=False,
        )
        self._worker = threading.Thread(
            target=self._sync_worker, name="gateway-api-sync", daemon=True
        )
        self._worker.start()
        try:
            while not self.stop_event.is_set():
                if not self._session_active():
                    self.stop_event.wait(1.0)
                    continue
                try:
                    if not self._camera_open:
                        self.camera.open()
                        self._camera_open = True
                        log_event(
                            logger,
                            logging.INFO,
                            "gateway_camera_opened",
                            camera_index=self.config.camera.index,
                            requested_width=self.config.camera.width,
                            requested_height=self.config.camera.height,
                            requested_fps=self.config.camera.fps,
                        )
                    ok, frame = self.camera.read()
                    if not ok or frame is None:
                        raise CameraUnavailableError("Camera frame read failed.")
                    assessment = self.processor.assess(frame)
                    now = time.monotonic()
                    if not self._quality_ok(assessment):
                        continue
                    periodic_due = (
                        now - self._last_periodic_at >= settings.periodic_burst_seconds
                    )
                    motion_candidate = (
                        assessment.motion_score >= settings.motion_threshold
                    )
                    cooldown_complete = (
                        now - self._last_burst_at
                        >= settings.minimum_burst_interval_seconds
                    )
                    if cooldown_complete and (periodic_due or motion_candidate):
                        if periodic_due:
                            self._last_periodic_at = now
                        self._last_burst_at = now
                        frames = self._capture_burst(frame, assessment)
                        if frames:
                            self._submit_burst(frames)
                    self.stop_event.wait(1.0 / self.config.camera.fps)
                except ApiCallError as exc:
                    log_event(
                        logger,
                        logging.WARNING,
                        "central_ai_burst_failed",
                        status_code=exc.status_code,
                        retryable=exc.retryable,
                    )
                except Exception as exc:
                    self.camera.close()
                    self._camera_open = False
                    log_event(
                        logger,
                        logging.WARNING,
                        "gateway_capture_retry",
                        exception_type=type(exc).__name__,
                    )
                    self.stop_event.wait(self.config.camera.reconnect_seconds)
        finally:
            self.stop_event.set()
            if self._worker is not None:
                self._worker.join(timeout=self.config.api.timeout_seconds + 1)
            self.camera.close()
            self._camera_open = False
            self.ai.close()
            self.api.close()
            self.outbox.close()
            log_event(logger, logging.INFO, "edge_agent_stopped", profile="STB_GATEWAY")

    def stop(self) -> None:
        self.stop_event.set()

    def _session_active(self) -> bool:
        starts_at = self.config.gateway.session_starts_at
        ends_at = self.config.gateway.session_ends_at
        now = datetime.now(UTC)
        if starts_at is not None and now < starts_at:
            return False
        if ends_at is not None and now >= ends_at:
            return False
        return True

    def _quality_ok(self, assessment: FrameAssessment) -> bool:
        settings = self.config.gateway
        return (
            settings.min_brightness <= assessment.brightness <= settings.max_brightness
            and assessment.sharpness >= settings.min_sharpness
        )

    def _capture_burst(
        self, first_frame: object, first_assessment: FrameAssessment
    ) -> list[BurstFrame]:
        captured: list[BurstFrame] = []
        frame = first_frame
        assessment = first_assessment
        for index in range(self.config.gateway.burst_frame_count):
            if self._quality_ok(assessment):
                encoded = self.processor.encode_jpeg(
                    frame, self.config.gateway.jpeg_quality
                )
                if encoded:
                    captured.append(BurstFrame(encoded, datetime.now(UTC)))
            if index + 1 < self.config.gateway.burst_frame_count:
                self.stop_event.wait(self.config.gateway.burst_frame_interval_seconds)
                ok, next_frame = self.camera.read()
                if not ok or next_frame is None:
                    break
                frame = next_frame
                assessment = self.processor.assess(frame)
        return captured

    def _submit_burst(self, frames: list[BurstFrame]) -> None:
        # A burst is one short track: a later person at the same camera must
        # not inherit temporal evidence from the previous candidate.
        track_id = f"camera-{self.config.camera.index}-{uuid4()}"
        decision = self.ai.recognize_burst(
            session_id=self.session_id,
            track_id=track_id,
            frames=frames,
        )
        payload = _event_payload(
            decision,
            device_id=self.device_id,
            occurred_at=frames[-1].captured_at,
        )
        try:
            self.outbox.enqueue(payload)
        except OutboxFullError:
            log_event(logger, logging.ERROR, "event_queue_full")
            return
        log_event(
            logger,
            logging.INFO,
            "central_ai_decision_queued",
            recognition_outcome=decision.outcome,
            reason_code=decision.reason_code,
        )

    def _sync_worker(self) -> None:
        next_heartbeat = 0.0
        while not self.stop_event.is_set():
            now = time.monotonic()
            if now >= next_heartbeat:
                try:
                    self.api.heartbeat()
                    log_event(logger, logging.DEBUG, "device_heartbeat_sent")
                except ApiCallError as exc:
                    log_event(
                        logger,
                        logging.WARNING,
                        "device_heartbeat_failed",
                        status_code=exc.status_code,
                        retryable=exc.retryable,
                    )
                next_heartbeat = now + self.config.api.heartbeat_interval_seconds
            for queued_event in self.outbox.due(limit=50):
                try:
                    self.api.submit_recognition_event(queued_event.payload)
                except ApiCallError as exc:
                    if exc.retryable:
                        self.outbox.retry(
                            queued_event.event_id,
                            max_delay_seconds=self.config.runtime.max_retry_seconds,
                            status_code=exc.status_code,
                        )
                        log_event(
                            logger,
                            logging.WARNING,
                            "recognition_event_delivery_retry",
                            status_code=exc.status_code,
                            attempt=queued_event.attempts + 1,
                        )
                        break
                    self.outbox.dead_letter(
                        queued_event.event_id, status_code=exc.status_code
                    )
                    log_event(
                        logger,
                        logging.ERROR,
                        "recognition_event_dead_lettered",
                        status_code=exc.status_code,
                    )
                else:
                    self.outbox.acknowledge(queued_event.event_id)
                    log_event(logger, logging.INFO, "recognition_event_delivered")
            self.stop_event.wait(1.0)


def _event_payload(
    decision: CentralDecision, *, device_id: UUID, occurred_at: datetime
) -> dict[str, object]:
    matched = decision.outcome == "matched"
    return {
        "event_id": str(uuid4()),
        "device_id": str(device_id),
        "session_id": str(decision.session_id),
        "student_id": str(decision.student_id) if decision.student_id else None,
        "outcome": decision.outcome,
        # Central AI returns confidence, not cosine similarity. Keep the
        # similarity field empty instead of deriving a misleading value.
        "similarity": None,
        "confidence": round(decision.confidence, 6)
        if decision.confidence is not None
        else None,
        "margin": round(decision.margin, 6)
        if decision.margin is not None and decision.margin <= 1.0
        else None,
        "liveness_passed": (
            True
            if matched and decision.liveness_score is not None
            else False
            if decision.reason_code is not None
            and (
                decision.reason_code.startswith("liveness")
                or decision.reason_code == "spoof"
            )
            else None
        ),
        "liveness_score": round(decision.liveness_score, 6)
        if decision.liveness_score is not None
        else None,
        "occurred_at": occurred_at.isoformat(),
        "model_name": "opencv-zoo-sface",
        "model_version": decision.model_version,
    }
