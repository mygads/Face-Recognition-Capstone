from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from presensi_edge_agent.config import EdgeConfig
from recognition_core.domain import (
    BoundingBox,
    FaceDetection,
    FrameObservation,
    GalleryEntry,
    TrackDecision,
)
from recognition_core.liveness import LivenessConfig
from recognition_core.matching import CosineSimilarityMatcher
from recognition_core.onnx_liveness import ONNXRuntimeAntiSpoofMN3
from recognition_core.opencv_models import SFaceModel, YuNetConfig, YuNetFaceDetector
from recognition_core.opencv_quality import OpenCVFaceQualityAssessor
from recognition_core.pipeline import RecognitionPipeline
from recognition_core.protocols import ImageFrame
from recognition_core.temporal import MultiFrameDecisionEngine, TemporalDecisionConfig


class IdentityPreprocessor:
    """Keep the camera frame unchanged; model stages consume it without persistence."""

    def preprocess(self, frame: ImageFrame) -> ImageFrame:
        return frame


def build_pipeline(config: EdgeConfig) -> RecognitionPipeline:
    if config.models.yunet_path is None or not config.models.yunet_path.is_file():
        raise ValueError("A locally provisioned YuNet model is required.")
    if config.models.sface_path is None or not config.models.sface_path.is_file():
        raise ValueError("A locally provisioned SFace model is required.")
    if (
        config.recognition.min_top1_similarity is None
        or config.recognition.min_top1_top2_margin is None
    ):
        raise ValueError("Recognition thresholds must be calibrated in config.")
    assert config.models.yunet_path is not None
    assert config.models.sface_path is not None
    assert config.recognition.min_top1_similarity is not None
    assert config.recognition.min_top1_top2_margin is not None
    detector: Any = YuNetFaceDetector(
        config.models.yunet_path,
        YuNetConfig(
            score_threshold=config.recognition.yunet_score_threshold,
            nms_threshold=config.recognition.yunet_nms_threshold,
        ),
    )
    if config.recognition.detection_max_width > 0:
        # Weak lab PCs: detect on a downscaled copy (~9x fewer pixels at
        # 640px vs 1920px) and map boxes back. Quality, alignment, and
        # embeddings still run on the full-resolution frame, so the
        # acceptance path is unchanged apart from detector recall, which
        # must be confirmed by the local calibration report.
        detector = DownscalingDetector(
            detector, max_width=config.recognition.detection_max_width
        )
    sface = SFaceModel(config.models.sface_path, model_version=config.models.version)
    liveness_config = LivenessConfig(
        enabled=config.liveness.enabled,
        required=config.liveness.required,
        min_live_score=config.liveness.min_live_score,
    )
    liveness_model = None
    if config.liveness.enabled:
        assert config.models.liveness_path is not None
        assert config.models.liveness_version is not None
        liveness_model = ONNXRuntimeAntiSpoofMN3(
            config.models.liveness_path,
            model_version=config.models.liveness_version,
        )
    return RecognitionPipeline(
        preprocessor=IdentityPreprocessor(),
        detector=detector,
        quality_assessor=OpenCVFaceQualityAssessor(
            min_face_pixels=config.quality.min_face_pixels,
            min_laplacian_variance=config.quality.min_laplacian_variance,
            min_brightness=config.quality.min_brightness,
            max_brightness=config.quality.max_brightness,
        ),
        aligner=sface,
        liveness_config=liveness_config,
        liveness_model=liveness_model,
        embedder=sface,
        matcher=CosineSimilarityMatcher(),
        temporal_decision=MultiFrameDecisionEngine(
            TemporalDecisionConfig(
                min_top1_similarity=config.recognition.min_top1_similarity,
                min_top1_top2_margin=config.recognition.min_top1_top2_margin,
                minimum_agreeing_frames=config.recognition.minimum_agreeing_frames,
                sample_every_n_frames=config.recognition.sample_every_n_frames,
                best_frame_count=config.recognition.best_frame_count,
                max_history_frames=config.recognition.max_history_frames,
                track_ttl_seconds=config.recognition.track_ttl_seconds,
            )
        ),
    )


class DownscalingDetector:
    """Run detection on a downscaled copy and map boxes to full resolution.

    YuNet cost scales with input pixels, so capping detector width is the
    cheapest lever for weak CPUs. Only the detector sees the small copy;
    quality assessment, alignment, and embeddings keep the original frame.
    """

    def __init__(self, inner: Any, *, max_width: int) -> None:
        if max_width < 320:
            raise ValueError("max_width must be at least 320 pixels.")
        self._inner = inner
        self._max_width = max_width
        self._cv2: Any | None = None

    def _resizer(self) -> Any:
        if self._cv2 is None:
            import importlib

            self._cv2 = importlib.import_module("cv2")
        return self._cv2

    def detect(self, frame: ImageFrame) -> tuple[FaceDetection, ...]:
        shape = getattr(frame, "shape", None)
        if shape is None or len(shape) < 2:
            return tuple(self._inner.detect(frame))
        height, width = int(shape[0]), int(shape[1])
        if width <= self._max_width or width < 1 or height < 1:
            return tuple(self._inner.detect(frame))
        scale = self._max_width / width
        small_height = max(1, round(height * scale))
        cv2 = self._resizer()
        small = cv2.resize(
            frame, (self._max_width, small_height), interpolation=cv2.INTER_AREA
        )
        detections = self._inner.detect(small)
        upscale = width / self._max_width
        rescaled: list[FaceDetection] = []
        for detection in detections:
            box = detection.box
            rescaled.append(
                FaceDetection(
                    box=BoundingBox(
                        min(max(0.0, box.x * upscale), float(width)),
                        min(max(0.0, box.y * upscale), float(height)),
                        max(1e-6, box.width * upscale),
                        max(1e-6, box.height * upscale),
                    ),
                    confidence=detection.confidence,
                    landmarks=tuple(
                        (x * upscale, y * upscale) for x, y in detection.landmarks
                    ),
                )
            )
        return tuple(rescaled)


class LocalRecognizer:
    """Run the shared recognition-core pipeline for one UVC camera stream."""

    def __init__(
        self,
        pipeline: RecognitionPipeline | None,
        device_id: UUID,
        *,
        diagnostic_only: bool = False,
    ) -> None:
        self.pipeline = pipeline
        self.track_id = f"camera-{device_id}"
        # Diagnostic recognizers drive preview/calibration display only and
        # must never feed the attendance-event outbox. The service submit
        # path enforces this via require_attendance_recognizer().
        self.diagnostic_only = diagnostic_only
        self._pipeline_lock = threading.RLock()
        self._timing_observer: Callable[[str, float], None] | None = None

    def set_timing_observer(
        self, observer: Callable[[str, float], None] | None
    ) -> None:
        self._timing_observer = observer

    def process(
        self,
        frame: object,
        gallery: tuple[GalleryEntry, ...],
        captured_at: datetime,
    ) -> TrackDecision:
        with self._pipeline_lock:
            if self.pipeline is None:
                raise RuntimeError("Recognition is waiting for calibrated settings.")
            # The temporal engine needs candidates from distinct students to apply
            # Top-1 vs Top-2 correctly when the gallery has multiple templates per
            # student. Return all template matches; the engine collapses by student.
            self.pipeline.max_candidates = max(2, len(gallery))
            observer = self._timing_observer
            started = time.perf_counter_ns() if observer is not None else 0
            decision = self.pipeline.process(
                frame,
                gallery,
                FrameObservation(track_id=self.track_id, captured_at=captured_at),
                timing_observer=observer,
            )
            if observer is not None:
                observer(
                    "pipeline_total_ms",
                    (time.perf_counter_ns() - started) / 1_000_000,
                )
            return decision

    def apply_configuration(self, config: EdgeConfig) -> None:
        next_pipeline = (
            build_pipeline(config)
            if config.recognition.min_top1_similarity is not None
            and config.recognition.min_top1_top2_margin is not None
            else None
        )
        with self._pipeline_lock:
            self.pipeline = next_pipeline

    def reset(self) -> None:
        with self._pipeline_lock:
            if self.pipeline is None:
                return
            temporal_engine = cast(Any, self.pipeline.temporal_decision)
            temporal_engine.reset_track(self.track_id)
