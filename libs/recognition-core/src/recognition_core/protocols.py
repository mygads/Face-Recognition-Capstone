from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from recognition_core.domain import (
    CandidateMatch,
    FaceDetection,
    FaceEmbedding,
    FaceQuality,
    FrameObservation,
    GalleryEntry,
    LivenessDecision,
    TrackDecision,
)

ImageFrame = object
AlignedFace = object


class Preprocessor(Protocol):
    def preprocess(self, frame: ImageFrame) -> ImageFrame: ...


class FaceDetector(Protocol):
    def detect(self, frame: ImageFrame) -> Sequence[FaceDetection]: ...


class FaceQualityAssessor(Protocol):
    def assess(self, frame: ImageFrame, detection: FaceDetection) -> FaceQuality: ...


class FaceAligner(Protocol):
    def align(self, frame: ImageFrame, detection: FaceDetection) -> AlignedFace: ...


class LivenessModel(Protocol):
    def evaluate(self, face: AlignedFace) -> LivenessDecision: ...


class FaceEmbedder(Protocol):
    def embed(self, face: AlignedFace) -> FaceEmbedding: ...


class Matcher(Protocol):
    def match(
        self,
        probe: FaceEmbedding,
        gallery: Sequence[GalleryEntry],
        *,
        limit: int = 2,
    ) -> Sequence[CandidateMatch]: ...


class TemporalDecisionEngine(Protocol):
    def decide(
        self,
        observation: FrameObservation,
        matches: Sequence[CandidateMatch],
        quality: FaceQuality,
        liveness: LivenessDecision,
    ) -> TrackDecision: ...
