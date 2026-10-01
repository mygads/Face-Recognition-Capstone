from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from presensi_edge_agent.api import ApiCallError, CoreApiClient
from presensi_edge_agent.cache import (
    ActiveSessionCache,
    CacheSchemaError,
    SessionCacheBundle,
    parse_session_cache,
)
from presensi_edge_agent.camera import CameraUnavailableError
from presensi_edge_agent.config import EdgeConfig, resolve_api_token
from presensi_edge_agent.events import event_payload
from presensi_edge_agent.logging import log_event
from presensi_edge_agent.outbox import EventOutbox, OutboxFullError
from recognition_core.domain import GalleryEntry, TrackDecision

logger = logging.getLogger("presensi_edge_agent")


class CameraSource(Protocol):
    def open(self) -> None: ...

    def read(self) -> tuple[bool, object | None]: ...

    def close(self) -> None: ...


class FrameRecognizer(Protocol):
    def process(
        self,
        frame: object,
        gallery: tuple[GalleryEntry, ...],
        captured_at: datetime,
    ) -> TrackDecision: ...

    def reset(self) -> None: ...


CacheFetch = Callable[[], dict[str, object]]


class EdgeService:
    """Run camera inference independently from API synchronization and retries."""

    def __init__(
        self,
        config: EdgeConfig,
        camera: CameraSource,
        api: CoreApiClient,
        outbox: EventOutbox,
        recognizer: FrameRecognizer,
        cache_fetch: CacheFetch,
    ) -> None:
        if config.device_id is None:
            raise ValueError("device_id is required to run the edge service.")
        self.config = config
        self.device_id = config.device_id
        self.camera = camera
        self.api = api
        if isinstance(api, CoreApiClient):
            api.set_camera_status_provider(
                lambda: "online" if self._camera_open else "offline"
            )
        self.outbox = outbox
        self.recognizer = recognizer
        self.cache_fetch = cache_fetch
        self.cache = ActiveSessionCache()
        self.stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._active_session_id: UUID | None = None
        self._active_bundle: SessionCacheBundle | None = None
        self._gallery: tuple[GalleryEntry, ...] = ()
        self._last_decision: tuple[str, str | None, str | None] | None = None
        self._camera_open = False

    def status(self) -> dict[str, object]:
        bundle = self.cache.current()
        pending, dead_letter = self.outbox.counts()
        return {
            "service": "presensi-edge-agent",
            "profile": "AI_EDGE",
            "device_id_configured": self.config.device_id is not None,
            "camera_open": self._camera_open,
            "session_cache_loaded": bundle is not None,
            "active_session_id": str(bundle.session_id) if bundle else None,
            "cached_student_count": len(bundle.students) if bundle else 0,
            "cached_template_count": (
                sum(len(student.templates) for student in bundle.students)
                if bundle
                else 0
            ),
            "pending_events": pending,
            "dead_letter_events": dead_letter,
        }

    def run(self) -> None:
        token = resolve_api_token(self.config)
        self.config.require_runtime(api_token=token)
        log_event(
            logger,
            logging.INFO,
            "edge_agent_starting",
            profile="AI_EDGE",
            camera_index=self.config.camera.index,
            capture_width=self.config.camera.width,
            capture_height=self.config.camera.height,
            requested_camera_fps=self.config.camera.fps,
            ai_sample_every_n_frames=self.config.recognition.sample_every_n_frames,
        )
        self._worker = threading.Thread(
            target=self._sync_worker,
            name="edge-api-sync",
            daemon=True,
        )
        self._worker.start()
        try:
            while not self.stop_event.is_set():
                try:
                    if not self._camera_open:
                        self.camera.open()
                        self._camera_open = True
                        log_event(
                            logger,
                            logging.INFO,
                            "camera_opened",
                            camera_index=self.config.camera.index,
                            requested_width=self.config.camera.width,
                            requested_height=self.config.camera.height,
                            requested_fps=self.config.camera.fps,
                        )
                    ok, frame = self.camera.read()
                    if not ok or frame is None:
                        raise CameraUnavailableError("Camera frame read failed.")
                except Exception as exc:
                    self.camera.close()
                    self._camera_open = False
                    log_event(
                        logger,
                        logging.WARNING,
                        "camera_capture_retry",
                        camera_index=self.config.camera.index,
                        exception_type=type(exc).__name__,
                    )
                    self.stop_event.wait(self.config.camera.reconnect_seconds)
                    continue
                try:
                    self._process_frame(frame)
                except Exception as exc:
                    self.recognizer.reset()
                    self._last_decision = None
                    log_event(
                        logger,
                        logging.ERROR,
                        "recognition_frame_failed",
                        exception_type=type(exc).__name__,
                    )
        finally:
            self.stop_event.set()
            if self._worker is not None:
                self._worker.join(timeout=self.config.api.timeout_seconds + 1)
            self.camera.close()
            self._camera_open = False
            self.api.close()
            self.outbox.close()
            log_event(logger, logging.INFO, "edge_agent_stopped")

    def stop(self) -> None:
        self.stop_event.set()

    def _process_frame(self, frame: object) -> None:
        bundle = self.cache.current()
        if bundle is None:
            if self._active_session_id is not None:
                expired_session_id = str(self._active_session_id)
                self._active_session_id = None
                self._active_bundle = None
                self._gallery = ()
                self._last_decision = None
                self.recognizer.reset()
                log_event(
                    logger,
                    logging.WARNING,
                    "active_session_cache_expired_or_cleared",
                    session_id=expired_session_id,
                )
            return
        session_changed = bundle.session_id != self._active_session_id
        cache_changed = (
            self._active_bundle is None
            or bundle.generated_at != self._active_bundle.generated_at
        )
        if session_changed:
            self._active_session_id = bundle.session_id
            self._last_decision = None
            self.recognizer.reset()
            log_event(
                logger,
                logging.INFO,
                "active_session_cache_loaded",
                cached_student_count=len(bundle.students),
                cached_template_count=sum(
                    len(student.templates) for student in bundle.students
                ),
            )
        if cache_changed:
            self._gallery = bundle.gallery()
        self._active_bundle = bundle
        captured_at = datetime.now(UTC)
        decision = self.recognizer.process(frame, self._gallery, captured_at)
        if decision.state == "collecting":
            return
        signature = (
            decision.state,
            str(decision.decision.student_id)
            if decision.decision.student_id is not None
            else None,
            decision.decision.reason_code,
        )
        if signature == self._last_decision:
            return
        self._last_decision = signature
        payload = event_payload(
            decision,
            device_id=self.device_id,
            session_id=bundle.session_id,
            occurred_at=captured_at,
            model_name="opencv-zoo-sface",
            model_version=self.config.models.version,
            liveness_required=self.config.liveness.required,
            liveness_enabled=self.config.liveness.enabled,
            min_live_score=self.config.liveness.min_live_score,
        )
        try:
            self.outbox.enqueue(payload)
        except OutboxFullError:
            log_event(logger, logging.ERROR, "event_queue_full")
            return
        except ValueError as exc:
            log_event(
                logger,
                logging.ERROR,
                "event_queue_rejected",
                exception_type=type(exc).__name__,
            )
            return
        pending, _ = self.outbox.counts()
        log_event(
            logger,
            logging.INFO,
            "recognition_event_queued",
            recognition_outcome=str(payload["outcome"]),
            pending_events=pending,
        )

    def _sync_worker(self) -> None:
        next_heartbeat = 0.0
        next_cache_refresh = 0.0
        while not self.stop_event.is_set():
            now = time.monotonic()
            try:
                if now >= next_heartbeat:
                    self._send_heartbeat()
                    next_heartbeat = now + self.config.api.heartbeat_interval_seconds
                if now >= next_cache_refresh:
                    refreshed = self._refresh_cache()
                    retry_delay = self.config.api.cache_refresh_seconds
                    if not refreshed:
                        retry_delay = max(retry_delay, 30.0)
                    next_cache_refresh = now + retry_delay
                self._flush_outbox()
            except Exception as exc:
                log_event(
                    logger,
                    logging.ERROR,
                    "edge_sync_cycle_failed",
                    exception_type=type(exc).__name__,
                )
            self.stop_event.wait(1.0)

    def _send_heartbeat(self) -> None:
        try:
            self.api.heartbeat()
        except ApiCallError as exc:
            log_event(
                logger,
                logging.WARNING,
                "device_heartbeat_failed",
                status_code=exc.status_code,
                retryable=exc.retryable,
            )
            return
        log_event(logger, logging.DEBUG, "device_heartbeat_sent")

    def _refresh_cache(self) -> bool:
        try:
            payload = self.cache_fetch()
            bundle = parse_session_cache(
                payload,
                device_id=self.device_id,
                model_name="opencv-zoo-sface",
                model_version=self.config.models.version,
                max_offline_seconds=self.config.api.cache_max_offline_seconds,
            )
        except ApiCallError as exc:
            log_event(
                logger,
                logging.WARNING,
                "session_cache_refresh_failed",
                status_code=exc.status_code,
                retryable=exc.retryable,
            )
            return False
        except CacheSchemaError as exc:
            log_event(
                logger,
                logging.WARNING,
                "session_cache_rejected",
                reason=str(exc),
            )
            return False
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                "session_cache_refresh_failed",
                exception_type=type(exc).__name__,
            )
            return False
        self.cache.replace(bundle)
        log_event(
            logger,
            logging.DEBUG,
            "session_cache_refreshed",
            cached_student_count=len(bundle.students),
            cached_template_count=sum(
                len(student.templates) for student in bundle.students
            ),
        )
        return True

    def _flush_outbox(self) -> None:
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
                    queued_event.event_id,
                    status_code=exc.status_code,
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
