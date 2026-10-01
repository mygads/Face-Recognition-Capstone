"""Framework-independent face-recognition domain and pipeline contracts."""

from recognition_core.domain import (
    BoundingBox,
    CandidateMatch,
    FaceDetection,
    FaceEmbedding,
    FaceQuality,
    FrameObservation,
    GalleryEntry,
    LivenessDecision,
    RecognitionDecision,
    TrackDecision,
    TrackStatus,
)
from recognition_core.liveness import LivenessConfig
from recognition_core.matching import CosineSimilarityMatcher, cosine_similarity
from recognition_core.onnx_liveness import ONNXRuntimeAntiSpoofMN3
from recognition_core.opencv_models import SFaceModel, YuNetConfig, YuNetFaceDetector
from recognition_core.pipeline import RecognitionPipeline
from recognition_core.protocols import (
    FaceAligner,
    FaceDetector,
    FaceEmbedder,
    FaceQualityAssessor,
    LivenessModel,
    Matcher,
    Preprocessor,
    TemporalDecisionEngine,
)
from recognition_core.temporal import MultiFrameDecisionEngine, TemporalDecisionConfig

__all__ = [
    "BoundingBox",
    "CandidateMatch",
    "CosineSimilarityMatcher",
    "FaceDetection",
    "FaceAligner",
    "FaceDetector",
    "FaceEmbedding",
    "FaceEmbedder",
    "FaceQuality",
    "FaceQualityAssessor",
    "FrameObservation",
    "GalleryEntry",
    "LivenessDecision",
    "LivenessConfig",
    "LivenessModel",
    "Matcher",
    "Preprocessor",
    "RecognitionDecision",
    "RecognitionPipeline",
    "SFaceModel",
    "TrackDecision",
    "TrackStatus",
    "TemporalDecisionEngine",
    "TemporalDecisionConfig",
    "MultiFrameDecisionEngine",
    "ONNXRuntimeAntiSpoofMN3",
    "YuNetConfig",
    "YuNetFaceDetector",
    "cosine_similarity",
]
