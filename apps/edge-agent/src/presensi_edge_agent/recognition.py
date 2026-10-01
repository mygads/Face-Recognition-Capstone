from __future__ import annotations

import importlib
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from presensi_edge_agent.config import EdgeConfig
from recognition_core.domain import (
    FaceDetection,
    FaceQuality,
    FrameObservation,
    GalleryEntry,
    TrackDecision,
)
from recognition_core.liveness import LivenessConfig
from recognition_core.matching import CosineSimilarityMatcher
from recognition_core.onnx_liveness import ONNXRuntimeAntiSpoofMN3
from recognition_core.opencv_models import SFaceModel, YuNetConfig, YuNetFaceDetector
from recognition_core.pipeline import RecognitionPipeline
from recognition_core.protocols import ImageFrame
from recognition_core.temporal import MultiFrameDecisionEngine, TemporalDecisionConfig


class IdentityPreprocessor:
    """Keep the camera frame unchanged; model stages consume it without persistence."""

    def preprocess(self, frame: ImageFrame) -> ImageFrame:
        return frame


class OpenCVFaceQualityAssessor:
    def __init__(
        self,
        *,
        min_face_pixels: int,
        min_laplacian_variance: float,
        min_brightness: float,
        max_brightness: float,
    ) -> None:
        self._cv2 = importlib.import_module("cv2")
        self._numpy = importlib.import_module("numpy")
        self.min_face_pixels = min_face_pixels
        self.min_laplacian_variance = min_laplacian_variance
        self.min_brightness = min_brightness
        self.max_brightness = max_brightness

    def assess(self, frame: ImageFrame, detection: FaceDetection) -> FaceQuality:
        image = cast(Any, frame)
        height, width = int(image.shape[0]), int(image.shape[1])
        box = detection.box
        left = max(0, int(box.x))
        top = max(0, int(box.y))
        right = min(width, int(box.x + box.width))
        bottom = min(height, int(box.y + box.height))
        crop = image[top:bottom, left:right]
        if crop.size == 0:
            return FaceQuality(
                score=0.0,
                acceptable=False,
                reason_codes=("face_crop_empty",),
            )

        gray = self._cv2.cvtColor(crop, self._cv2.COLOR_BGR2GRAY)
        brightness = float(self._numpy.mean(gray))
        sharpness = float(self._cv2.Laplacian(gray, self._cv2.CV_64F).var())
        face_size = min(right - left, bottom - top)
        reasons: list[str] = []
        if face_size < self.min_face_pixels:
            reasons.append("face_too_small")
        if sharpness < self.min_laplacian_variance:
            reasons.append("frame_blurry")
        if not self.min_brightness <= brightness <= self.max_brightness:
            reasons.append("lighting_out_of_range")
        size_score = min(1.0, face_size / self.min_face_pixels)
        sharpness_score = (
            1.0
            if self.min_laplacian_variance == 0
            else min(1.0, sharpness / self.min_laplacian_variance)
        )
        if brightness < self.min_brightness:
            lighting_score = brightness / max(self.min_brightness, 1.0)
        elif brightness > self.max_brightness:
            lighting_score = self.max_brightness / max(brightness, 1.0)
        else:
            lighting_score = 1.0
        return FaceQuality(
            score=min(size_score, sharpness_score, lighting_score),
            acceptable=not reasons,
            signals=(
                ("face_size_px", float(face_size)),
                ("sharpness", sharpness),
                ("brightness", brightness),
            ),
            reason_codes=tuple(reasons),
        )


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

    def __init__(self, pipeline: RecognitionPipeline, device_id: UUID) -> None:
        self.pipeline = pipeline
        self.track_id = f"camera-{device_id}"

    def process(
        self,
        frame: object,
        gallery: tuple[GalleryEntry, ...],
        captured_at: datetime,
    ) -> TrackDecision:
        # The temporal engine needs candidates from distinct students to apply
        # Top-1 vs Top-2 correctly when the gallery has multiple templates per
        # student. Return all template matches; the engine collapses by student.
        self.pipeline.max_candidates = max(2, len(gallery))
        return self.pipeline.process(
            frame,
            gallery,
            FrameObservation(track_id=self.track_id, captured_at=captured_at),
        )

    def reset(self) -> None:
        temporal_engine = cast(Any, self.pipeline.temporal_decision)
        temporal_engine.reset_track(self.track_id)
