from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from presensi_ai_service.config import AISettings
from presensi_ai_service.gallery_cache import SessionGallery
from recognition_core.domain import FrameObservation, TrackDecision
from recognition_core.liveness import LivenessConfig
from recognition_core.matching import CosineSimilarityMatcher
from recognition_core.opencv_models import SFaceModel, YuNetConfig, YuNetFaceDetector
from recognition_core.opencv_quality import OpenCVFaceQualityAssessor
from recognition_core.pipeline import RecognitionPipeline
from recognition_core.protocols import ImageFrame
from recognition_core.temporal import MultiFrameDecisionEngine, TemporalDecisionConfig


class InferenceBusyError(RuntimeError):
    """The single model runtime is still busy with timed-out inference."""


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    image: ImageFrame
    captured_at: datetime


class IdentityPreprocessor:
    def preprocess(self, frame: ImageFrame) -> ImageFrame:
        return frame


class RecognitionRunner:
    """Serializes access to one reusable shared recognition-core pipeline."""

    def __init__(self, pipeline: RecognitionPipeline) -> None:
        self.pipeline = pipeline
        self._pipeline_lock = threading.Lock()
        self._slot = threading.BoundedSemaphore(1)
        self._track_ids: dict[tuple[UUID, UUID], set[str]] = {}

    async def process_burst(
        self,
        *,
        device_id: UUID,
        session_id: UUID,
        track_id: str,
        frames: tuple[CapturedFrame, ...],
        gallery: SessionGallery,
        timeout_seconds: float,
    ) -> TrackDecision:
        if not self._slot.acquire(blocking=False):
            raise InferenceBusyError("The inference worker is busy.")

        async def run() -> TrackDecision:
            try:
                return await asyncio.to_thread(
                    self._process_burst_sync,
                    device_id,
                    session_id,
                    track_id,
                    frames,
                    gallery,
                )
            finally:
                self._slot.release()

        task = asyncio.create_task(run())

        def consume_background_error(completed: asyncio.Task[TrackDecision]) -> None:
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(consume_background_error)
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout_seconds)
        except TimeoutError:
            # Shield lets the worker finish safely, while the slot remains held
            # until its finally block runs. New bursts fail fast in the meantime.
            raise

    def _process_burst_sync(
        self,
        device_id: UUID,
        session_id: UUID,
        track_id: str,
        frames: tuple[CapturedFrame, ...],
        gallery: SessionGallery,
    ) -> TrackDecision:
        scoped_track_id = f"{device_id}:{session_id}:{track_id}"
        session_key = (device_id, session_id)
        with self._pipeline_lock:
            # Top-1/Top-2 must be computed over unique students after the core's
            # temporal engine collapses multiple enrolled templates per person.
            self.pipeline.max_candidates = max(2, len(gallery.entries))
            decision: TrackDecision | None = None
            for frame in frames:
                decision = self.pipeline.process(
                    frame.image,
                    gallery.entries,
                    FrameObservation(
                        track_id=scoped_track_id,
                        captured_at=frame.captured_at,
                    ),
                )
            if decision is None:
                raise RuntimeError("An inference burst did not contain frames.")
            self._track_ids.setdefault(session_key, set()).add(scoped_track_id)
            return decision

    def invalidate_session(self, device_id: UUID, session_id: UUID) -> None:
        key = (device_id, session_id)
        with self._pipeline_lock:
            track_ids = self._track_ids.pop(key, set())
            reset_track = getattr(self.pipeline.temporal_decision, "reset_track", None)
            if callable(reset_track):
                for track_id in track_ids:
                    reset_track(track_id)


def build_model_runner(settings: AISettings) -> RecognitionRunner | None:
    """Build local model adapters only when explicitly provisioned and calibrated."""
    model_paths = (settings.yunet_model_path, settings.sface_model_path)
    if all(path is None for path in model_paths):
        return None
    if any(path is None or not path.is_file() for path in model_paths):
        raise ValueError("Both configured YuNet and SFace model files must exist.")
    if not settings.model_version:
        raise ValueError("PRESENSI_AI_MODEL_VERSION must be configured.")
    if settings.min_top1_similarity is None or settings.min_top1_top2_margin is None:
        raise ValueError(
            "Recognition thresholds must be explicitly calibrated in configuration."
        )
    yunet_path, sface_path = model_paths
    assert yunet_path is not None and sface_path is not None
    sface = SFaceModel(sface_path, model_version=settings.model_version)
    liveness_model: Any | None = None
    if settings.liveness_enabled:
        from recognition_core.onnx_liveness import ONNXRuntimeAntiSpoofMN3

        assert settings.liveness_model_path is not None
        assert settings.liveness_model_version is not None
        liveness_model = ONNXRuntimeAntiSpoofMN3(
            settings.liveness_model_path,
            model_version=settings.liveness_model_version,
        )
    pipeline = RecognitionPipeline(
        preprocessor=IdentityPreprocessor(),
        detector=YuNetFaceDetector(yunet_path, YuNetConfig()),
        quality_assessor=OpenCVFaceQualityAssessor(
            min_face_pixels=settings.min_face_pixels,
            min_laplacian_variance=settings.min_laplacian_variance,
            min_brightness=settings.min_brightness,
            max_brightness=settings.max_brightness,
        ),
        aligner=sface,
        liveness_config=LivenessConfig(
            enabled=settings.liveness_enabled,
            required=settings.liveness_required,
            min_live_score=settings.liveness_min_score,
        ),
        liveness_model=liveness_model,
        embedder=sface,
        matcher=CosineSimilarityMatcher(),
        temporal_decision=MultiFrameDecisionEngine(
            TemporalDecisionConfig(
                min_top1_similarity=settings.min_top1_similarity,
                min_top1_top2_margin=settings.min_top1_top2_margin,
                minimum_agreeing_frames=settings.minimum_agreeing_frames,
                sample_every_n_frames=settings.sample_every_n_frames,
                best_frame_count=settings.best_frame_count,
                max_history_frames=settings.max_history_frames,
            )
        ),
    )
    return RecognitionRunner(pipeline)
