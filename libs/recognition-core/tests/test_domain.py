from datetime import UTC, datetime
from uuid import UUID

import pytest

from recognition_core.domain import (
    BoundingBox,
    CandidateMatch,
    FaceDetection,
    FaceEmbedding,
    FaceQuality,
    FrameObservation,
    RecognitionDecision,
    TrackDecision,
)


def test_domain_values_validate_ranges_and_required_identity() -> None:
    student_id = UUID(int=11)
    embedding = FaceEmbedding(
        values=(0.3, 0.4),
        model_name="synthetic",
        model_version="test",
        normalized=False,
    )

    assert CandidateMatch(student_id, similarity=-0.2).similarity == -0.2
    assert FaceQuality(score=0.8, acceptable=True).acceptable
    assert FaceDetection(BoundingBox(0, 0, 20, 20), confidence=1.0).confidence == 1.0
    assert embedding.values == (0.3, 0.4)
    assert FrameObservation("track", datetime.now(UTC)).track_id == "track"

    with pytest.raises(ValueError):
        BoundingBox(0, 0, 0, 20)
    with pytest.raises(ValueError):
        CandidateMatch(student_id, similarity=1.1)
    with pytest.raises(ValueError):
        RecognitionDecision(outcome="matched")
    with pytest.raises(ValueError):
        RecognitionDecision(outcome="no_match", student_id=student_id)


def test_track_retry_requires_frontal_request_and_matched_acceptance() -> None:
    with pytest.raises(ValueError):
        TrackDecision(
            track_id="track",
            state="retry_frontal",
            decision=RecognitionDecision(outcome="retry"),
            observation_count=1,
        )

    accepted = TrackDecision(
        track_id="track",
        state="accepted",
        decision=RecognitionDecision(
            outcome="matched",
            student_id=UUID(int=12),
            confidence=0.9,
            margin=0.2,
        ),
        observation_count=3,
    )
    assert accepted.state == "accepted"
