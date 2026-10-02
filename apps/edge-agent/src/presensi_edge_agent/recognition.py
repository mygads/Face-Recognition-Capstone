from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from presensi_edge_agent.config import EdgeConfig
from recognition_core.domain import (
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
        detector=YuNetFaceDetector(config.models.yunet_path, YuNetConfig()),
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


class LocalRecognizer:
    """Run the shared recognition-core pipeline for one UVC camera stream."""

    def __init__(self, pipeline: RecognitionPipeline | None, device_id: UUID) -> None:
        self.pipeline = pipeline
        self.track_id = f"camera-{device_id}"
        self._pipeline_lock = threading.RLock()

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
            return self.pipeline.process(
                frame,
                gallery,
                FrameObservation(track_id=self.track_id, captured_at=captured_at),
            )

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
