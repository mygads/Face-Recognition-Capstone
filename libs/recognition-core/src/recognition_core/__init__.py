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
    "TrackDecision",
    "TemporalDecisionEngine",
]
