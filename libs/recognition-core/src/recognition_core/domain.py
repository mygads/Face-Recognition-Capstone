from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

Point = tuple[float, float]
DecisionOutcome = Literal["matched", "ambiguous", "no_match", "retry", "error"]
TrackState = Literal["collecting", "accepted", "retry_frontal", "rejected"]
TrackStatus = Literal[
    "COLLECTING",
    "ACCEPTED",
    "NEED_FRONTAL_RETRY",
    "REJECTED",
]
LivenessState = Literal["live", "spoof", "inconclusive"]


def _unit_interval(name: str, value: float | None) -> None:
    if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
        raise ValueError(f"{name} must be finite and between 0 and 1.")


@dataclass(frozen=True, slots=True)
class BoundingBox:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if not all(
            math.isfinite(value) for value in (self.x, self.y, self.width, self.height)
        ):
            raise ValueError("Bounding-box coordinates must be finite.")
        if self.x < 0 or self.y < 0 or self.width <= 0 or self.height <= 0:
            raise ValueError(
                "Bounding box must have a non-negative origin and positive size."
            )


@dataclass(frozen=True, slots=True)
class FaceDetection:
    box: BoundingBox
    confidence: float
    landmarks: tuple[Point, ...] = ()

    def __post_init__(self) -> None:
        _unit_interval("confidence", self.confidence)
        if any(
            len(point) != 2
            or not all(math.isfinite(coordinate) for coordinate in point)
            for point in self.landmarks
        ):
            raise ValueError("Landmarks must contain finite x/y coordinates.")


@dataclass(frozen=True, slots=True)
class FaceQuality:
    score: float
    acceptable: bool
    signals: tuple[tuple[str, float], ...] = ()
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _unit_interval("quality score", self.score)
        if any(not name or not math.isfinite(value) for name, value in self.signals):
            raise ValueError("Quality signals need names and finite values.")


@dataclass(frozen=True, slots=True)
class FaceEmbedding:
    values: tuple[float, ...]
    model_name: str
    model_version: str
    normalized: bool

    def __post_init__(self) -> None:
        if not self.values or not all(math.isfinite(value) for value in self.values):
            raise ValueError("Embedding must contain finite numeric values.")
        if not self.model_name.strip() or not self.model_version.strip():
            raise ValueError("Embedding model name and version are required.")


@dataclass(frozen=True, slots=True)
class GalleryEntry:
    student_id: UUID
    embedding: FaceEmbedding


@dataclass(frozen=True, slots=True)
class CandidateMatch:
    student_id: UUID
    similarity: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.similarity) or not -1 <= self.similarity <= 1:
            raise ValueError("Cosine similarity must be finite and between -1 and 1.")


@dataclass(frozen=True, slots=True)
class LivenessDecision:
    state: LivenessState
    confidence: float | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        _unit_interval("liveness confidence", self.confidence)


@dataclass(frozen=True, slots=True)
class RecognitionDecision:
    outcome: DecisionOutcome
    student_id: UUID | None = None
    confidence: float | None = None
    margin: float | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        _unit_interval("confidence", self.confidence)
        _unit_interval("margin", self.margin)
        if self.outcome == "matched" and self.student_id is None:
            raise ValueError("A matched decision must name a student.")
        if self.outcome != "matched" and self.student_id is not None:
            raise ValueError("Only a matched decision can name a student.")


@dataclass(frozen=True, slots=True)
class TrackDecision:
    track_id: str
    state: TrackState
    decision: RecognitionDecision
    observation_count: int
    needs_frontal_look: bool = False

    def __post_init__(self) -> None:
        if not self.track_id.strip():
            raise ValueError("Track id is required.")
        if self.observation_count < 0:
            raise ValueError("Observation count cannot be negative.")
        if self.state == "accepted" and self.decision.outcome != "matched":
            raise ValueError("Accepted tracks must contain a matched decision.")
        if self.state == "retry_frontal" and not self.needs_frontal_look:
            raise ValueError("Frontal retry state must request a frontal look.")

    @property
    def status(self) -> TrackStatus:
        """Expose stable machine status names while preserving domain state names."""
        if self.state == "collecting":
            return "COLLECTING"
        if self.state == "accepted":
            return "ACCEPTED"
        if self.state == "retry_frontal":
            return "NEED_FRONTAL_RETRY"
        return "REJECTED"


@dataclass(frozen=True, slots=True)
class FrameObservation:
    track_id: str
    captured_at: datetime

    def __post_init__(self) -> None:
        if not self.track_id.strip():
            raise ValueError("Track id is required.")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("Frame observation time must be timezone-aware.")
