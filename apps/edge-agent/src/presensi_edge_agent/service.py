from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from presensi_edge_agent.api import ApiCallError, CoreApiClient
from presensi_edge_agent.cache import (
    ActiveSessionCache,
    CacheSchemaError,
    SessionCacheBundle,
    parse_preview_gallery,
    parse_session_cache,
)
from presensi_edge_agent.camera import CameraUnavailableError
from presensi_edge_agent.camera_diagnostics import (
    CameraFrameInspector,
    build_camera_frame_inspector,
)
from presensi_edge_agent.config import EdgeConfig, resolve_api_token
from presensi_edge_agent.events import event_payload
from presensi_edge_agent.local_preview import LocalCameraPreview
from presensi_edge_agent.logging import log_event
from presensi_edge_agent.managed_config import (
    apply_managed_configuration,
    persist_managed_configuration,
)
from presensi_edge_agent.outbox import EventOutbox, OutboxFullError
from presensi_edge_agent.performance import EdgePerformanceMonitor
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
                lambda: (
                    "disabled"
                    if not self._camera_enabled
                    else "online"
                    if self._camera_open
                    else "offline"
                )
            )
        self.outbox = outbox
        self.recognizer = recognizer
        self.performance = EdgePerformanceMonitor.from_environment()
        self._set_recognizer_timing_observer(recognizer)
        self.cache_fetch = cache_fetch
        self.cache = ActiveSessionCache()
        self.stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._capture_thread: threading.Thread | None = None
        self._frame_condition = threading.Condition()
        self._latest_frame: object | None = None
        self._frame_sequence = 0
        self._active_session_id: UUID | None = None
        self._active_bundle: SessionCacheBundle | None = None
        self._preview_bundle: SessionCacheBundle | None = None
        self._gallery: tuple[GalleryEntry, ...] = ()
        self._last_decision: tuple[str, str | None, str | None] | None = None
        self._calibration_recognizer: FrameRecognizer | None = None
        self._preview_recognizer: FrameRecognizer | None = None
        self._last_preview_probe_at = 0.0
        self._preview_diagnostic_error_reported = False
        self._camera_frame_inspector: CameraFrameInspector | None = None
        self._camera_inspector_attempted = False
        self._last_camera_inspection = 0.0
        self._camera_inspector_error_reported = False
        self._camera_open = False
        self._camera_enabled = True
        self.preview_cache = ActiveSessionCache()
        self.preview = (
            LocalCameraPreview(config)
            if config.mode == "AI_EDGE" and config.preview.enabled
            else None
        )

    def status(self) -> dict[str, object]:
        bundle = self.cache.current()
        pending, dead_letter = self.outbox.counts()
        return {
            "service": "presensi-edge-agent",
            "profile": "AI_EDGE",
            "device_id_configured": self.config.device_id is not None,
            "camera_open": self._camera_open,
            "camera_enabled": self._camera_enabled,
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
            "runtime_config_revision": self.config.runtime_config_revision,
            "recognition_ready": (
                self.config.recognition.min_top1_similarity is not None
                and self.config.recognition.min_top1_top2_margin is not None
            ),
        }

    def run(self) -> None:
        token = resolve_api_token(self.config)
        self.config.require_runtime(api_token=token, allow_unconfigured_thresholds=True)
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
            performance_logging_enabled=self.performance is not None,
        )
        self._worker = threading.Thread(
            target=self._sync_worker,
            name="edge-api-sync",
            daemon=True,
        )
        self._worker.start()
        if self.preview is not None:
            try:
                self.preview.start()
                self.preview.update_status(
                    camera_open=False,
                    session_active=False,
                    recognition_state="starting",
                )
                log_event(
                    logger,
                    logging.INFO,
                    "local_camera_preview_started",
                    bind_host=self.config.preview.bind_host,
                    port=self.config.preview.port,
                )
            except OSError as exc:
                self.preview = None
                log_event(
                    logger,
                    logging.WARNING,
                    "local_camera_preview_unavailable",
                    exception_type=type(exc).__name__,
                )
        try:
            self._capture_thread = threading.Thread(
                target=self._capture_loop,
                name="edge-camera-capture",
                daemon=True,
            )
            self._capture_thread.start()
            last_sequence = 0
            while not self.stop_event.is_set():
                captured = self._next_camera_frame(last_sequence)
                if captured is None:
                    continue
                last_sequence, frame = captured
                if frame is None or not self._camera_enabled:
                    continue
                if self.preview is not None:
                    self._update_camera_diagnostics(frame)
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
                if self.performance is not None:
                    self.performance.maybe_log()
        finally:
            self.stop_event.set()
            with self._frame_condition:
                self._frame_condition.notify_all()
            if self._capture_thread is not None:
                self._capture_thread.join(
                    timeout=max(2.0, self.config.api.timeout_seconds)
                )
            if self._worker is not None:
                self._worker.join(timeout=self.config.api.timeout_seconds + 1)
            self.camera.close()
            self._camera_open = False
            if self.preview is not None:
                self.preview.update_status(
                    camera_open=False,
                    recognition_state="stopped",
                    display_name=None,
                )
                self.preview.stop()
            self.api.close()
            self.outbox.close()
            log_event(logger, logging.INFO, "edge_agent_stopped")

    def _capture_loop(self) -> None:
        try:
            while not self.stop_event.is_set():
                if not self._camera_enabled:
                    if self._camera_open:
                        self.camera.close()
                        self._camera_open = False
                    self._publish_camera_frame(None)
                    if self.preview is not None:
                        self.preview.clear_frame()
                        self.preview.update_diagnostic_candidate(None, None)
                        self.preview.update_status(
                            camera_open=False,
                            recognition_state="camera_disabled",
                            display_name=None,
                        )
                    self.stop_event.wait(0.25)
                    continue
                try:
                    if not self._camera_open:
                        self.camera.open()
                        self._camera_open = True
                        if self.preview is not None:
                            self.preview.update_status(camera_open=True)
                        actual_mode = self._reported_camera_mode() or {}
                        log_event(
                            logger,
                            logging.INFO,
                            "camera_opened",
                            camera_index=self.config.camera.index,
                            requested_width=self.config.camera.width,
                            requested_height=self.config.camera.height,
                            requested_fps=self.config.camera.fps,
                            actual_width=actual_mode.get("width"),
                            actual_height=actual_mode.get("height"),
                            actual_fps=actual_mode.get("fps"),
                        )
                    read_started = time.perf_counter_ns()
                    ok, frame = self.camera.read()
                    if self.performance is not None:
                        self.performance.observe(
                            "camera_read_ms",
                            (time.perf_counter_ns() - read_started) / 1_000_000,
                        )
                    if not ok or frame is None:
                        raise CameraUnavailableError("Camera frame read failed.")
                    if self.performance is not None:
                        self.performance.increment("camera_frames")
                    if self.preview is not None and self.preview.has_active_viewer():
                        preview_started = time.perf_counter_ns()
                        if (
                            self.preview.update_frame(frame)
                            and self.performance is not None
                        ):
                            self.performance.increment("preview_frames")
                            self.performance.observe(
                                "preview_encode_ms",
                                (time.perf_counter_ns() - preview_started) / 1_000_000,
                            )
                    self._publish_camera_frame(frame)
                    if self.performance is not None:
                        self.performance.maybe_log()
                except Exception as exc:
                    self.camera.close()
                    self._camera_open = False
                    self._publish_camera_frame(None)
                    if self.preview is not None:
                        self.preview.clear_frame()
                        self.preview.update_status(
                            camera_open=False,
                            recognition_state="camera_unavailable",
                            display_name=None,
                        )
                    log_event(
                        logger,
                        logging.WARNING,
                        "camera_capture_retry",
                        camera_index=self.config.camera.index,
                        exception_type=type(exc).__name__,
                    )
                    self.stop_event.wait(self.config.camera.reconnect_seconds)
        finally:
            self.camera.close()
            self._camera_open = False
            self._publish_camera_frame(None)

    def _publish_camera_frame(self, frame: object | None) -> None:
        with self._frame_condition:
            self._latest_frame = frame
            self._frame_sequence += 1
            self._frame_condition.notify_all()

    def _next_camera_frame(
        self, last_sequence: int
    ) -> tuple[int, object | None] | None:
        with self._frame_condition:
            self._frame_condition.wait_for(
                lambda: (
                    self._frame_sequence > last_sequence or self.stop_event.is_set()
                ),
                timeout=0.25,
            )
            if self._frame_sequence <= last_sequence:
                return None
            return self._frame_sequence, self._latest_frame

    def stop(self) -> None:
        self.stop_event.set()

    def _set_recognizer_timing_observer(self, recognizer: FrameRecognizer) -> None:
        configure_observer = getattr(recognizer, "set_timing_observer", None)
        if callable(configure_observer):
            configure_observer(
                self.performance.observe if self.performance is not None else None
            )

    def _reported_camera_mode(self) -> dict[str, int | float] | None:
        get_mode = getattr(self.camera, "reported_mode", None)
        if not callable(get_mode):
            return None
        try:
            mode = get_mode()
        except Exception:
            return None
        return mode if isinstance(mode, dict) else None

    def _update_camera_diagnostics(self, frame: object) -> None:
        preview = self.preview
        if preview is None or not preview.has_active_viewer():
            return
        now = time.monotonic()
        if now - self._last_camera_inspection < 0.75:
            return
        self._last_camera_inspection = now
        try:
            if not self._camera_inspector_attempted:
                pipeline = getattr(self.recognizer, "pipeline", None)
                detector = getattr(pipeline, "detector", None)
                quality_assessor = getattr(pipeline, "quality_assessor", None)
                if detector is not None and quality_assessor is not None:
                    self._camera_frame_inspector = CameraFrameInspector(
                        detector,
                        quality_assessor,
                    )
                else:
                    self._camera_frame_inspector = build_camera_frame_inspector(
                        self.config
                    )
                self._camera_inspector_attempted = True
            assert self._camera_frame_inspector is not None
            inspect_started = time.perf_counter_ns()
            observation = self._camera_frame_inspector.inspect(frame)
            if self.performance is not None:
                self.performance.observe(
                    "camera_diagnostics_ms",
                    (time.perf_counter_ns() - inspect_started) / 1_000_000,
                )
            preview.update_camera_observation(observation.as_payload())
            self._camera_inspector_error_reported = False
        except Exception as exc:
            message = (
                "Model deteksi wajah belum tersedia. Jalankan installer model AI_EDGE."
                if isinstance(exc, FileNotFoundError)
                else "Pemeriksaan wajah gagal. Periksa model YuNet dan log agent."
            )
            preview.update_camera_observation(
                {
                    "state": "unavailable",
                    "message": message,
                    "frame_width": 0,
                    "frame_height": 0,
                    "face_count": 0,
                    "faces": [],
                }
            )
            if not self._camera_inspector_error_reported:
                log_event(
                    logger,
                    logging.WARNING,
                    "camera_preview_diagnostics_unavailable",
                    exception_type=type(exc).__name__,
                )
                self._camera_inspector_error_reported = True

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
                if self.preview is not None:
                    self.preview.update_status(
                        session_active=False,
                        recognition_state="waiting_for_session",
                        display_name=None,
                    )
                log_event(
                    logger,
                    logging.WARNING,
                    "active_session_cache_expired_or_cleared",
                    session_id=expired_session_id,
                )
            preview_bundle = self.preview_cache.current()
            if preview_bundle is not None:
                self._process_preview_only_frame(frame, preview_bundle)
                return
            self._preview_bundle = None
            if self.preview is not None:
                self.preview.clear_calibration_session()
                self.preview.update_status(
                    session_active=False,
                    recognition_state="waiting_for_session",
                    display_name=None,
                )
                self.preview.update_diagnostic_candidate(None, None)
                self.preview.update_attendance_result(None)
            return
        self.preview_cache.clear()
        self._preview_bundle = None
        if bundle.session_id is None:
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
            if self.preview is not None:
                self.preview.clear_calibration_session()
                self.preview.update_attendance_result(None)
                self.preview.update_status(
                    session_active=True,
                    recognition_state="waiting_for_calibration"
                    if self.config.recognition.min_top1_similarity is None
                    or self.config.recognition.min_top1_top2_margin is None
                    else "checking",
                    display_name=None,
                )
                self.preview.update_diagnostic_candidate(None, None)
        if cache_changed:
            if self._calibration_recognizer is not None:
                self._calibration_recognizer.reset()
                self._calibration_recognizer = None
            if self._preview_recognizer is not None:
                self._preview_recognizer.reset()
                self._preview_recognizer = None
            self._last_preview_probe_at = 0.0
            self._preview_diagnostic_error_reported = False
            self._gallery = bundle.gallery()
            if self.preview is not None:
                self.preview.update_calibration_students(
                    tuple(
                        (student.student_id, student.full_name)
                        for student in bundle.students
                        if student.templates
                    ),
                    gallery_identity_count=len(
                        {entry.student_id for entry in self._gallery}
                    ),
                )
        self._active_bundle = bundle
        if self.preview is not None and self.preview.calibration_request() is not None:
            self._process_calibration_frame(frame)
            return
        if (
            self.config.recognition.min_top1_similarity is None
            or self.config.recognition.min_top1_top2_margin is None
        ):
            if self.preview is not None:
                self.preview.update_status(
                    session_active=True,
                    recognition_state="waiting_for_calibration",
                    display_name=None,
                )
                has_viewer = self.preview.has_active_viewer()
                if not has_viewer or not self._gallery:
                    self.preview.update_diagnostic_candidate(None, None)
                    if not has_viewer and self._preview_recognizer is not None:
                        self._preview_recognizer.reset()
                        self._preview_recognizer = None
                    return
                now = time.monotonic()
                if now - self._last_preview_probe_at >= 0.8:
                    self._last_preview_probe_at = now
                    self._process_live_preview_candidate(frame, bundle)
            return
        if self.preview is not None:
            self.preview.update_diagnostic_candidate(None, None)
        captured_at = datetime.now(UTC)
        decision = self.recognizer.process(frame, self._gallery, captured_at)
        if self.preview is not None:
            display_name = None
            if (
                decision.state == "accepted"
                and decision.decision.student_id is not None
            ):
                matched_student = next(
                    (
                        student
                        for student in bundle.students
                        if student.student_id == decision.decision.student_id
                    ),
                    None,
                )
                display_name = matched_student.full_name if matched_student else None
            self.preview.update_status(
                session_active=True,
                recognition_state=decision.state,
                display_name=display_name,
            )
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
        if self.preview is not None and payload.get("outcome") == "matched":
            self.preview.update_attendance_result("pending")
        pending, _ = self.outbox.counts()
        log_event(
            logger,
            logging.INFO,
            "recognition_event_queued",
            recognition_outcome=str(payload["outcome"]),
            pending_events=pending,
        )

    def _process_preview_only_frame(
        self, frame: object, bundle: SessionCacheBundle
    ) -> None:
        """Identify a lab-scoped candidate for display only; never make attendance."""
        preview = self.preview
        if preview is None:
            return
        changed = (
            self._preview_bundle is None
            or bundle.generated_at != self._preview_bundle.generated_at
        )
        if changed:
            self._preview_bundle = bundle
            self._gallery = bundle.gallery()
            if self._preview_recognizer is not None:
                self._preview_recognizer.reset()
                self._preview_recognizer = None
            self._last_preview_probe_at = 0.0
        preview.update_status(
            session_active=False,
            recognition_state="preview_only",
            display_name=None,
        )
        preview.update_attendance_result(None)
        if not preview.has_active_viewer() or not self._gallery:
            preview.update_diagnostic_candidate(None, None)
            if self._preview_recognizer is not None:
                self._preview_recognizer.reset()
                self._preview_recognizer = None
            return
        now = time.monotonic()
        if now - self._last_preview_probe_at >= 0.8:
            self._last_preview_probe_at = now
            self._process_live_preview_candidate(frame, bundle)

    def _process_live_preview_candidate(
        self, frame: object, bundle: SessionCacheBundle
    ) -> None:
        """Show an ephemeral top candidate to an operator; never enqueue an event."""
        preview = self.preview
        if preview is None:
            return
        try:
            if self._preview_recognizer is None:
                self._preview_recognizer = self._create_preview_recognizer()
                self._set_recognizer_timing_observer(self._preview_recognizer)
            decision = self._preview_recognizer.process(
                frame,
                self._gallery,
                datetime.now(UTC),
            )
            self._preview_diagnostic_error_reported = False
            student_id = decision.decision.student_id
            confidence = decision.decision.confidence
            if decision.state != "accepted" or student_id is None or confidence is None:
                preview.update_diagnostic_candidate(None, None)
                return
            student = next(
                (item for item in bundle.students if item.student_id == student_id),
                None,
            )
            if student is None:
                preview.update_diagnostic_candidate(None, None)
                return
            # recognition-core normalizes cosine similarity to [0, 1] for its
            # decision object; restore the raw cosine value for an honest label.
            preview.update_diagnostic_candidate(
                student.full_name,
                2 * confidence - 1,
                " · ".join(student.class_names),
            )
        except Exception as exc:
            preview.update_diagnostic_candidate(None, None)
            self._last_preview_probe_at = time.monotonic() + 4.0
            if not self._preview_diagnostic_error_reported:
                log_event(
                    logger,
                    logging.WARNING,
                    "live_preview_diagnostic_unavailable",
                    exception_type=type(exc).__name__,
                )
                self._preview_diagnostic_error_reported = True
            self._preview_recognizer = None
        finally:
            if self._preview_recognizer is not None:
                self._preview_recognizer.reset()

    def _create_preview_recognizer(self) -> FrameRecognizer:
        """Use one quality-checked frame for a non-attendance camera preview."""
        if self.config.device_id is None:
            raise ValueError("device_id is required for live preview diagnostics.")
        from presensi_edge_agent.recognition import LocalRecognizer, build_pipeline

        diagnostic_recognition = replace(
            self.config.recognition,
            min_top1_similarity=-1.0,
            min_top1_top2_margin=0.0,
            minimum_agreeing_frames=1,
            sample_every_n_frames=1,
            best_frame_count=1,
            max_history_frames=1,
        )
        diagnostic_config = replace(self.config, recognition=diagnostic_recognition)
        return LocalRecognizer(build_pipeline(diagnostic_config), self.device_id)

    def _process_calibration_frame(self, frame: object) -> None:
        preview = self.preview
        if preview is None:
            return
        try:
            if self._calibration_recognizer is None:
                self._calibration_recognizer = self._create_calibration_recognizer()
                self._set_recognizer_timing_observer(self._calibration_recognizer)
            decision = self._calibration_recognizer.process(
                frame,
                self._gallery,
                datetime.now(UTC),
            )
        except Exception:
            preview.fail_calibration_sample("calibration_error")
            self._calibration_recognizer = None
            log_event(logger, logging.ERROR, "local_calibration_probe_failed")
            return
        if decision.state == "collecting":
            return
        try:
            request = preview.calibration_request()
            if request is None:
                return
            if decision.state != "accepted" or decision.decision.student_id is None:
                preview.fail_calibration_sample(
                    decision.decision.reason_code
                    or (
                        "no_candidate"
                        if decision.state == "rejected"
                        else "liveness_inconclusive"
                        if decision.state == "retry_frontal"
                        else "try_again"
                    )
                )
                return
            confidence = decision.decision.confidence
            margin = decision.decision.margin
            if confidence is None or margin is None:
                preview.fail_calibration_sample("invalid_score")
                return
            phase = request["phase"]
            expected_student_id = request["student_id"]
            expected_identity_match = (
                str(decision.decision.student_id) == expected_student_id
                if phase == "genuine"
                else None
            )
            preview.complete_calibration_sample(
                top1_similarity=2 * confidence - 1,
                top1_top2_margin=2 * margin,
                expected_identity_match=expected_identity_match,
            )
        finally:
            if self._calibration_recognizer is not None:
                self._calibration_recognizer.reset()

    def _create_calibration_recognizer(self) -> FrameRecognizer:
        """Build an ephemeral permissive probe; it never submits attendance events."""
        if self.config.device_id is None:
            raise ValueError("device_id is required for local calibration.")
        from presensi_edge_agent.recognition import LocalRecognizer, build_pipeline

        diagnostic_recognition = replace(
            self.config.recognition,
            min_top1_similarity=-1.0,
            min_top1_top2_margin=0.0,
        )
        diagnostic_config = replace(self.config, recognition=diagnostic_recognition)
        return LocalRecognizer(build_pipeline(diagnostic_config), self.device_id)

    def _sync_worker(self) -> None:
        next_heartbeat = 0.0
        next_cache_refresh = 0.0
        next_configuration_refresh = 0.0
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
                if now >= next_configuration_refresh:
                    self._sync_managed_configuration()
                    next_configuration_refresh = now + max(
                        15.0, self.config.api.heartbeat_interval_seconds
                    )
                self._flush_outbox()
            except Exception as exc:
                log_event(
                    logger,
                    logging.ERROR,
                    "edge_sync_cycle_failed",
                    exception_type=type(exc).__name__,
                )
            self.stop_event.wait(1.0)

    def _sync_managed_configuration(self) -> None:
        fetch = getattr(self.api, "fetch_runtime_configuration", None)
        report = getattr(self.api, "report_runtime_configuration", None)
        if not callable(fetch) or not callable(report):
            return
        attempted_revision = self.config.runtime_config_revision
        try:
            payload = fetch()
            camera_enabled = payload.get("camera_enabled", self._camera_enabled)
            if not isinstance(camera_enabled, bool):
                raise ValueError("invalid_camera_enabled")
            self._camera_enabled = camera_enabled
            revision = payload.get("revision")
            settings = payload.get("settings")
            if type(revision) is not int or revision < 0:
                raise ValueError("invalid_revision")
            attempted_revision = revision
            if revision == 0:
                return
            if revision < self.config.runtime_config_revision:
                raise ValueError("revision_rollback")
            if revision != self.config.runtime_config_revision:
                updated_config = apply_managed_configuration(
                    self.config, revision=revision, settings=settings
                )
                apply_recognition = getattr(
                    self.recognizer, "apply_configuration", None
                )
                if updated_config.mode == "AI_EDGE":
                    if not callable(apply_recognition):
                        raise ValueError("recognition_reconfigure_unavailable")
                    apply_recognition(updated_config)
                    self.recognizer.reset()
                if not isinstance(settings, dict):
                    raise ValueError("invalid_settings")
                persist_managed_configuration(
                    self.config, revision=revision, settings=settings
                )
                self.config = updated_config
                if self._preview_recognizer is not None:
                    self._preview_recognizer.reset()
                    self._preview_recognizer = None
                if self._calibration_recognizer is not None:
                    self._calibration_recognizer.reset()
                    self._calibration_recognizer = None
                self._last_preview_probe_at = 0.0
                self._preview_diagnostic_error_reported = False
                if self.preview is not None:
                    self.preview.update_diagnostic_candidate(None, None)
                self._camera_frame_inspector = None
                self._camera_inspector_attempted = False
            report(revision=revision, status="applied")
            log_event(
                logger,
                logging.INFO,
                "runtime_configuration_applied",
                config_revision=revision,
            )
        except ApiCallError as exc:
            log_event(
                logger,
                logging.WARNING,
                "runtime_configuration_fetch_failed",
                status_code=exc.status_code,
                retryable=exc.retryable,
            )
        except Exception as exc:
            error_code = (
                str(exc)
                if isinstance(exc, ValueError) and str(exc).replace("_", "").isalnum()
                else "configuration_apply_failed"
            )[:64]
            try:
                if callable(report) and attempted_revision > 0:
                    report(
                        revision=attempted_revision,
                        status="error",
                        error_code=error_code,
                    )
            except ApiCallError:
                pass
            log_event(
                logger,
                logging.ERROR,
                "runtime_configuration_apply_failed",
                error_code=error_code,
            )

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
            if exc.status_code in {404, 409}:
                self.cache.clear()
                if exc.status_code == 409:
                    self.preview_cache.clear()
                    return True
                return self._refresh_preview_gallery()
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
        self.preview_cache.clear()
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

    def _refresh_preview_gallery(self) -> bool:
        fetch = getattr(self.api, "fetch_preview_gallery", None)
        if not callable(fetch):
            self.preview_cache.clear()
            return False
        try:
            payload = fetch()
            bundle = parse_preview_gallery(
                payload,
                device_id=self.device_id,
                model_name="opencv-zoo-sface",
                model_version=self.config.models.version,
                max_offline_seconds=self.config.api.cache_max_offline_seconds,
            )
        except ApiCallError as exc:
            if exc.status_code in {404, 409}:
                self.preview_cache.clear()
                return True
            log_event(
                logger,
                logging.WARNING,
                "preview_gallery_refresh_failed",
                status_code=exc.status_code,
                retryable=exc.retryable,
            )
            return False
        except CacheSchemaError as exc:
            log_event(
                logger,
                logging.WARNING,
                "preview_gallery_rejected",
                reason=str(exc),
            )
            self.preview_cache.clear()
            return False
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                "preview_gallery_refresh_failed",
                exception_type=type(exc).__name__,
            )
            return False
        self.preview_cache.replace(bundle)
        return True

    def _flush_outbox(self) -> None:
        for queued_event in self.outbox.due(limit=50):
            delivery_started = time.perf_counter_ns()
            try:
                response = self.api.submit_recognition_event(queued_event.payload)
            except ApiCallError as exc:
                if self.performance is not None:
                    self.performance.observe(
                        "event_delivery_ms",
                        (time.perf_counter_ns() - delivery_started) / 1_000_000,
                    )
                    self.performance.increment("event_failed")
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
                if self.preview is not None:
                    display_name, class_name = self._preview_student_identity(
                        queued_event.payload.get("student_id")
                    )
                    self.preview.update_attendance_result(
                        "delivery_failed",
                        display_name=display_name,
                        class_name=class_name,
                    )
                log_event(
                    logger,
                    logging.ERROR,
                    "recognition_event_dead_lettered",
                    status_code=exc.status_code,
                )
            else:
                if self.performance is not None:
                    self.performance.observe(
                        "event_delivery_ms",
                        (time.perf_counter_ns() - delivery_started) / 1_000_000,
                    )
                    self.performance.increment("event_delivered")
                self._update_preview_attendance_result(
                    queued_event.payload,
                    response,
                )
                self.outbox.acknowledge(queued_event.event_id)
                log_event(logger, logging.INFO, "recognition_event_delivered")

    def _update_preview_attendance_result(
        self,
        payload: dict[str, object],
        response: object,
    ) -> None:
        preview = self.preview
        if (
            preview is None
            or self._active_session_id is None
            or payload.get("session_id") != str(self._active_session_id)
            or not isinstance(response, dict)
        ):
            return
        decision = response.get("decision")
        if decision == "attendance_recorded":
            attendance = response.get("attendance")
            status = attendance.get("status") if isinstance(attendance, dict) else None
            student_id = (
                attendance.get("student_id") if isinstance(attendance, dict) else None
            )
            bundle = self._active_bundle
            display_name = None
            class_name = None
            if (
                status in {"present", "late"}
                and isinstance(student_id, str)
                and bundle is not None
                and bundle.session_id == self._active_session_id
            ):
                matched_student = next(
                    (
                        student
                        for student in bundle.students
                        if str(student.student_id) == student_id
                    ),
                    None,
                )
                if matched_student is not None:
                    display_name = matched_student.full_name
                    class_name = " · ".join(matched_student.class_names)
            preview.update_attendance_result(
                "recorded",
                status if status in {"present", "late"} else None,
                display_name,
                class_name,
            )
        elif decision == "no_attendance":
            if response.get("reason") == "attendance_already_recorded":
                display_name, class_name = self._preview_student_identity(
                    payload.get("student_id")
                )
                preview.update_attendance_result(
                    "already_recorded", display_name=display_name, class_name=class_name
                )
            elif response.get("outcome") == "matched":
                preview.update_attendance_result("not_recorded")

    def _preview_student_identity(
        self, student_id: object
    ) -> tuple[str | None, str | None]:
        bundle = self._active_bundle
        if bundle is None or not isinstance(student_id, str):
            return None, None
        student = next(
            (item for item in bundle.students if str(item.student_id) == student_id),
            None,
        )
        if student is None:
            return None, None
        class_name = " · ".join(student.class_names) or None
        return student.full_name, class_name
