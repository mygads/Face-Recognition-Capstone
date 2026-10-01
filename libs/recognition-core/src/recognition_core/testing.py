"""Deterministic stage fakes for unit tests and example pipeline wiring."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

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
from recognition_core.protocols import AlignedFace, ImageFrame


class FakePreprocessor:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def preprocess(self, frame: ImageFrame) -> ImageFrame:
        self.calls.append("preprocess")
        return frame


class FakeFaceDetector:
    def __init__(self, calls: list[str], faces: Sequence[FaceDetection]) -> None:
        self.calls = calls
        self.faces = tuple(faces)

    def detect(self, frame: ImageFrame) -> Sequence[FaceDetection]:
        self.calls.append("detect")
        return self.faces


class FakeFaceQualityAssessor:
    def __init__(self, calls: list[str], result: FaceQuality) -> None:
        self.calls = calls
        self.result = result

    def assess(self, frame: ImageFrame, detection: FaceDetection) -> FaceQuality:
        self.calls.append("quality")
        return self.result


class FakeFaceAligner:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def align(self, frame: ImageFrame, detection: FaceDetection) -> AlignedFace:
        self.calls.append("align")
        return ("aligned-frame", frame)


class FakeLivenessModel:
    def __init__(self, calls: list[str], result: LivenessDecision) -> None:
        self.calls = calls
        self.result = result

    def evaluate(self, face: AlignedFace) -> LivenessDecision:
        self.calls.append("liveness")
        return self.result


class FakeFaceEmbedder:
    def __init__(self, calls: list[str], result: FaceEmbedding) -> None:
        self.calls = calls
        self.result = result

    def embed(self, face: AlignedFace) -> FaceEmbedding:
        self.calls.append("embed")
        return self.result


class FakeMatcher:
    def __init__(self, calls: list[str], results: Sequence[CandidateMatch]) -> None:
        self.calls = calls
        self.results = tuple(results)
        self.probe: FaceEmbedding | None = None
        self.gallery: Sequence[GalleryEntry] = ()

    def match(
        self,
        probe: FaceEmbedding,
        gallery: Sequence[GalleryEntry],
        *,
        limit: int = 2,
    ) -> Sequence[CandidateMatch]:
        self.calls.append("match")
        self.probe = probe
        self.gallery = gallery
        return self.results[:limit]


class FakeTemporalDecisionEngine:
    def __init__(self, calls: list[str], result: TrackDecision) -> None:
        self.calls = calls
        self.result = result
        self.observation: FrameObservation | None = None
        self.matches: Sequence[CandidateMatch] = ()
        self.quality: FaceQuality | None = None
        self.liveness: LivenessDecision | None = None
        self.sample_result = True

    def should_sample(self, observation: FrameObservation) -> bool:
        del observation
        self.calls.append("sample")
        return self.sample_result

    def on_skipped(self, observation: FrameObservation) -> TrackDecision:
        del observation
        self.calls.append("skip")
        return self.result

    def decide(
        self,
        observation: FrameObservation,
        matches: Sequence[CandidateMatch],
        quality: FaceQuality,
        liveness: LivenessDecision,
    ) -> TrackDecision:
        self.calls.append("temporal")
        self.observation = observation
        self.matches = matches
        self.quality = quality
        self.liveness = liveness
        return self.result


def dummy_gallery_entry(student_id: UUID, embedding: FaceEmbedding) -> GalleryEntry:
    return GalleryEntry(student_id=student_id, embedding=embedding)


def any_frame() -> ImageFrame:
    return object()
