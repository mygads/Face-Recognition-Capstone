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
)
from recognition_core.matching import CosineSimilarityMatcher, cosine_similarity
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
    "LivenessModel",
    "Matcher",
    "Preprocessor",
    "RecognitionDecision",
    "RecognitionPipeline",
    "SFaceModel",
    "TrackDecision",
    "TemporalDecisionEngine",
    "YuNetConfig",
    "YuNetFaceDetector",
    "cosine_similarity",
]
