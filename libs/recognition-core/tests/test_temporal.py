from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from recognition_core.domain import (
    CandidateMatch,
    FaceQuality,
    FrameObservation,
    LivenessDecision,
    TrackDecision,
)
from recognition_core.temporal import MultiFrameDecisionEngine, TemporalDecisionConfig

PERSON_A = UUID(int=101)
PERSON_B = UUID(int=202)
BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def _engine(
    *,
    sample_every_n_frames: int = 1,
    minimum_agreeing_frames: int = 3,
    best_frame_count: int = 3,
    max_history_frames: int = 5,
    min_top1_similarity: float = 0.8,
    min_top1_top2_margin: float = 0.2,
) -> MultiFrameDecisionEngine:
    return MultiFrameDecisionEngine(
        TemporalDecisionConfig(
            min_top1_similarity=min_top1_similarity,
            min_top1_top2_margin=min_top1_top2_margin,
            minimum_agreeing_frames=minimum_agreeing_frames,
            sample_every_n_frames=sample_every_n_frames,
            best_frame_count=best_frame_count,
            max_history_frames=max_history_frames,
        )
    )


def _observation(frame: int, track_id: str = "track-1") -> FrameObservation:
    return FrameObservation(
        track_id=track_id,
        captured_at=BASE_TIME + timedelta(milliseconds=frame * 100),
    )


def _matches(
    top1_id: UUID,
    top1_score: float,
    top2_id: UUID = PERSON_B,
    top2_score: float = 0.3,
) -> tuple[CandidateMatch, ...]:
    return (
        CandidateMatch(top1_id, top1_score),
        CandidateMatch(top2_id, top2_score),
    )


def _decide(
    engine: MultiFrameDecisionEngine,
    frame: int,
    matches: tuple[CandidateMatch, ...],
    *,
    quality: FaceQuality | None = None,
) -> TrackDecision:
    return engine.decide(
        _observation(frame),
        matches,
        quality or FaceQuality(score=0.9, acceptable=True),
        LivenessDecision(
            state="live",
            live_score=0.95,
            required=True,
            passed=True,
        ),
    )


def test_consistent_high_confidence_frames_accept_same_identity() -> None:
    engine = _engine()

    first = _decide(engine, 1, _matches(PERSON_A, 0.92))
    second = _decide(engine, 2, _matches(PERSON_A, 0.94))
    final = _decide(engine, 3, _matches(PERSON_A, 0.93))

    assert first.state == second.state == "collecting"
    assert final.state == "accepted"
    assert final.status == "ACCEPTED"
    assert final.decision.student_id == PERSON_A
    assert final.observation_count == 3
    assert final.decision.confidence == pytest.approx(0.965)
    assert final.decision.liveness_score == pytest.approx(0.95)


def test_close_top1_and_top2_margin_requests_frontal_retry() -> None:
    engine = _engine(min_top1_top2_margin=0.1)

    for frame in range(1, 4):
        result = _decide(
            engine,
            frame,
            _matches(PERSON_A, 0.92, PERSON_B, 0.89),
        )

    assert result.state == "retry_frontal"
    assert result.status == "NEED_FRONTAL_RETRY"
    assert result.decision.outcome == "ambiguous"
    assert result.decision.student_id is None
    assert result.needs_frontal_look is True
    assert result.decision.reason_code == "top1_top2_margin_too_small"


def test_top2_margin_compares_distinct_people_not_duplicate_templates() -> None:
    engine = _engine(
        minimum_agreeing_frames=2,
        best_frame_count=2,
        min_top1_top2_margin=0.5,
    )
    matches = (
        CandidateMatch(PERSON_A, 0.93),
        CandidateMatch(PERSON_A, 0.92),
        CandidateMatch(PERSON_B, 0.35),
    )
    _decide(engine, 1, matches)
    result = _decide(engine, 2, matches)

    assert result.state == "accepted"
    assert result.decision.student_id == PERSON_A


def test_top1_below_configured_threshold_is_rejected() -> None:
    engine = _engine(
        minimum_agreeing_frames=2,
        best_frame_count=2,
        min_top1_similarity=0.9,
    )
    _decide(engine, 1, _matches(PERSON_A, 0.85))
    result = _decide(engine, 2, _matches(PERSON_A, 0.86))

    assert result.state == "rejected"
    assert result.status == "REJECTED"
    assert result.decision.outcome == "no_match"
    assert result.decision.reason_code == "top1_below_threshold"


def test_unacceptable_quality_clears_prior_evidence_and_requests_retry() -> None:
    engine = _engine()
    _decide(engine, 1, _matches(PERSON_A, 0.95))
    poor_quality = _decide(
        engine,
        2,
        _matches(PERSON_A, 0.95),
        quality=FaceQuality(
            score=0.2,
            acceptable=False,
            reason_codes=("face_blurry",),
        ),
    )
    after_reset = _decide(engine, 3, _matches(PERSON_A, 0.95))
    still_collecting = _decide(engine, 4, _matches(PERSON_A, 0.95))

    assert poor_quality.status == "NEED_FRONTAL_RETRY"
    assert poor_quality.decision.reason_code == "face_blurry"
    assert after_reset.state == still_collecting.state == "collecting"
    assert still_collecting.observation_count == 2


def test_track_identity_change_discards_previous_person_evidence() -> None:
    engine = _engine(minimum_agreeing_frames=3, best_frame_count=3)
    first = _decide(engine, 1, _matches(PERSON_A, 0.94))
    second_a = _decide(engine, 2, _matches(PERSON_A, 0.95))
    changed = _decide(engine, 3, _matches(PERSON_B, 0.96, PERSON_A, 0.4))
    second_b = _decide(engine, 4, _matches(PERSON_B, 0.97, PERSON_A, 0.4))
    accepted_b = _decide(engine, 5, _matches(PERSON_B, 0.98, PERSON_A, 0.4))

    assert first.state == second_a.state == "collecting"
    assert changed.state == "collecting"
    assert changed.decision.student_id is None
    assert changed.observation_count == 1
    assert second_b.state == "collecting"
    assert second_b.observation_count == 2
    assert accepted_b.state == "accepted"
    assert accepted_b.decision.student_id == PERSON_B
    assert accepted_b.observation_count == 3


def test_only_best_quality_frames_are_aggregated() -> None:
    engine = _engine(
        minimum_agreeing_frames=2,
        best_frame_count=2,
        max_history_frames=3,
        min_top1_similarity=0.8,
        min_top1_top2_margin=0.1,
    )
    _decide(
        engine,
        1,
        _matches(PERSON_A, 0.95, PERSON_B, 0.2),
        quality=FaceQuality(score=0.95, acceptable=True),
    )
    _decide(
        engine,
        2,
        _matches(PERSON_A, 0.85, PERSON_B, 0.2),
        quality=FaceQuality(score=0.8, acceptable=True),
    )
    final = _decide(
        engine,
        3,
        _matches(PERSON_A, 0.82, PERSON_B, 0.2),
        quality=FaceQuality(score=0.2, acceptable=True),
    )

    assert final.state == "accepted"
    assert final.decision.confidence == pytest.approx(0.95)


def test_sampling_stride_skips_configured_intermediate_frames() -> None:
    engine = _engine(sample_every_n_frames=3)
    first = _observation(1)
    second = _observation(2)
    third = _observation(3)

    assert engine.should_sample(first) is True
    first_result = engine.decide(
        first,
        _matches(PERSON_A, 0.95),
        FaceQuality(score=0.9, acceptable=True),
        LivenessDecision(
            state="live",
            live_score=0.95,
            required=True,
            passed=True,
        ),
    )
    assert engine.should_sample(second) is False
    assert engine.on_skipped(second) == first_result
    assert engine.should_sample(third) is False
