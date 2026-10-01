"""Configurable quality-ranked temporal decisions for stable face tracks."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from recognition_core.domain import (
    CandidateMatch,
    FaceQuality,
    FrameObservation,
    LivenessDecision,
    RecognitionDecision,
    TrackDecision,
)


@dataclass(frozen=True, slots=True)
class TemporalDecisionConfig:
    """Runtime sampling and calibration settings.

    Score thresholds are required inputs so deployments must choose calibrated
    values explicitly. ``min_top1_top2_margin`` is a raw cosine-score difference
    in [0, 2]; the normalized margin returned in RecognitionDecision is [0, 1].
    """

    min_top1_similarity: float
    min_top1_top2_margin: float
    minimum_agreeing_frames: int = 3
    sample_every_n_frames: int = 2
    best_frame_count: int = 5
    max_history_frames: int = 10
    track_ttl_seconds: float = 3.0

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.min_top1_similarity)
            or not -1 <= self.min_top1_similarity <= 1
        ):
            raise ValueError("min_top1_similarity must be between -1 and 1.")
        if (
            not math.isfinite(self.min_top1_top2_margin)
            or not 0 <= self.min_top1_top2_margin <= 2
        ):
            raise ValueError("min_top1_top2_margin must be between 0 and 2.")
        if self.minimum_agreeing_frames < 1:
            raise ValueError("minimum_agreeing_frames must be positive.")
        if self.sample_every_n_frames < 1:
            raise ValueError("sample_every_n_frames must be positive.")
        if self.best_frame_count < self.minimum_agreeing_frames:
            raise ValueError(
                "best_frame_count must be at least minimum_agreeing_frames."
            )
        if self.max_history_frames < self.best_frame_count:
            raise ValueError("max_history_frames must be at least best_frame_count.")
        if not math.isfinite(self.track_ttl_seconds) or self.track_ttl_seconds <= 0:
            raise ValueError("track_ttl_seconds must be finite and positive.")


@dataclass(frozen=True, slots=True)
class _FrameEvidence:
    student_id: UUID
    top1_similarity: float
    top1_top2_margin: float
    quality_score: float
    sample_number: int


@dataclass(slots=True)
class _TrackState:
    frames_seen: int = 0
    sampled_frames: int = 0
    last_observed_at: datetime | None = None
    pending_sample: bool = False
    locked_student_id: UUID | None = None
    evidence: list[_FrameEvidence] = field(default_factory=list)
    last_decision: TrackDecision | None = None


class MultiFrameDecisionEngine:
    """Aggregate sampled evidence per upstream tracker ID.

    A stream should use one engine instance and supply the same ``track_id`` for
    each person across frames. When a sampled frame's Top-1 identity changes, all
    earlier evidence for that track ID is discarded before the new identity is
    considered.
    """

    def __init__(self, config: TemporalDecisionConfig) -> None:
        self.config = config
        self._tracks: dict[str, _TrackState] = {}

    def _state_for(self, observation: FrameObservation) -> _TrackState | None:
        expired_track_ids = [
            track_id
            for track_id, track in self._tracks.items()
            if track.last_observed_at is not None
            and (observation.captured_at - track.last_observed_at).total_seconds()
            > self.config.track_ttl_seconds
        ]
        for track_id in expired_track_ids:
            self._tracks.pop(track_id, None)

        state = self._tracks.get(observation.track_id)
        if state is None or state.last_observed_at is None:
            return self._tracks.setdefault(observation.track_id, _TrackState())

        elapsed = (observation.captured_at - state.last_observed_at).total_seconds()
        if elapsed > self.config.track_ttl_seconds:
            state = _TrackState()
            self._tracks[observation.track_id] = state
        elif elapsed <= 0:
            return None
        return state

    def should_sample(self, observation: FrameObservation) -> bool:
        """Select a deterministic stride before any image/model work is run."""
        state = self._state_for(observation)
        if state is None:
            return False
        state.last_observed_at = observation.captured_at
        state.frames_seen += 1
        state.pending_sample = (
            state.frames_seen - 1
        ) % self.config.sample_every_n_frames == 0
        return state.pending_sample

    def on_skipped(self, observation: FrameObservation) -> TrackDecision:
        state = self._tracks.get(observation.track_id)
        if state is not None and state.last_decision is not None:
            return state.last_decision
        return self._collecting_decision(
            observation.track_id,
            observation_count=0 if state is None else state.sampled_frames,
            reason_code="sampling_skipped",
        )

    def decide(
        self,
        observation: FrameObservation,
        matches: Sequence[CandidateMatch],
        quality: FaceQuality,
        liveness: LivenessDecision,
    ) -> TrackDecision:
        state = self._tracks.get(observation.track_id)
        if state is None or not state.pending_sample:
            if not self.should_sample(observation):
                return self.on_skipped(observation)
            state = self._tracks[observation.track_id]
        state.pending_sample = False
        state.sampled_frames += 1

        if not quality.acceptable:
            return self._reset_with_retry(
                observation.track_id,
                state,
                reason_code=(
                    quality.reason_codes[0]
                    if quality.reason_codes
                    else "quality_rejected"
                ),
            )
        if liveness.state == "spoof":
            return self._reset_with_rejection(
                observation.track_id,
                state,
                reason_code=liveness.reason_code or "spoof",
            )
        if liveness.state != "live":
            return self._reset_with_retry(
                observation.track_id,
                state,
                reason_code=liveness.reason_code or "liveness_inconclusive",
            )

        best_by_student: dict[UUID, float] = {}
        for match in matches:
            previous = best_by_student.get(match.student_id)
            if previous is None or match.similarity > previous:
                best_by_student[match.student_id] = match.similarity
        ranked = sorted(
            best_by_student.items(), key=lambda item: (-item[1], str(item[0]))
        )
        if not ranked:
            return self._reset_with_retry(
                observation.track_id,
                state,
                reason_code="no_candidate",
            )

        top1_student_id, top1_similarity = ranked[0]
        top2_similarity = ranked[1][1] if len(ranked) > 1 else -1.0
        raw_margin = max(0.0, top1_similarity - top2_similarity)

        if top1_similarity < self.config.min_top1_similarity:
            return self._reset_with_rejection(
                observation.track_id,
                state,
                reason_code="top1_below_threshold",
            )
        if raw_margin < self.config.min_top1_top2_margin:
            return self._reset_with_retry(
                observation.track_id,
                state,
                reason_code="top1_top2_margin_too_small",
                outcome="ambiguous",
            )

        if state.locked_student_id != top1_student_id:
            state.locked_student_id = top1_student_id
            state.evidence.clear()
            state.sampled_frames = 1

        state.evidence.append(
            _FrameEvidence(
                student_id=top1_student_id,
                top1_similarity=top1_similarity,
                top1_top2_margin=raw_margin,
                quality_score=quality.score,
                sample_number=state.frames_seen,
            )
        )
        state.evidence = sorted(
            state.evidence,
            key=lambda frame: (-frame.quality_score, -frame.sample_number),
        )[: self.config.max_history_frames]
        best_frames = state.evidence[: self.config.best_frame_count]
        result = self._decision_for_evidence(
            observation.track_id,
            state,
            best_frames,
        )
        state.last_decision = result
        return result

    def reset_track(self, track_id: str) -> None:
        """Forget evidence when the upstream tracker explicitly ends a track."""
        self._tracks.pop(track_id, None)

    def _decision_for_evidence(
        self,
        track_id: str,
        state: _TrackState,
        best_frames: list[_FrameEvidence],
    ) -> TrackDecision:
        student_id = state.locked_student_id
        if student_id is None or not best_frames:
            return self._collecting_decision(
                track_id,
                observation_count=state.sampled_frames,
                reason_code="awaiting_consensus",
            )

        if len(best_frames) < self.config.minimum_agreeing_frames:
            return self._collecting_decision(
                track_id,
                observation_count=state.sampled_frames,
                reason_code="awaiting_consensus",
            )

        average_top1 = sum(frame.top1_similarity for frame in best_frames) / len(
            best_frames
        )
        average_margin = sum(frame.top1_top2_margin for frame in best_frames) / len(
            best_frames
        )
        confidence = min(1.0, max(0.0, (average_top1 + 1) / 2))
        normalized_margin = min(1.0, max(0.0, average_margin / 2))

        if average_top1 < self.config.min_top1_similarity:
            return TrackDecision(
                track_id=track_id,
                state="rejected",
                decision=RecognitionDecision(
                    outcome="no_match",
                    confidence=confidence,
                    margin=normalized_margin,
                    reason_code="top1_below_threshold",
                ),
                observation_count=state.sampled_frames,
            )
        if average_margin < self.config.min_top1_top2_margin:
            return TrackDecision(
                track_id=track_id,
                state="retry_frontal",
                decision=RecognitionDecision(
                    outcome="ambiguous",
                    confidence=confidence,
                    margin=normalized_margin,
                    reason_code="top1_top2_margin_too_small",
                ),
                observation_count=state.sampled_frames,
                needs_frontal_look=True,
            )
        return TrackDecision(
            track_id=track_id,
            state="accepted",
            decision=RecognitionDecision(
                outcome="matched",
                student_id=student_id,
                confidence=confidence,
                margin=normalized_margin,
            ),
            observation_count=state.sampled_frames,
        )

    def _reset_with_retry(
        self,
        track_id: str,
        state: _TrackState,
        *,
        reason_code: str,
        outcome: Literal["retry", "ambiguous"] = "retry",
    ) -> TrackDecision:
        state.locked_student_id = None
        state.evidence.clear()
        result = TrackDecision(
            track_id=track_id,
            state="retry_frontal",
            decision=RecognitionDecision(outcome=outcome, reason_code=reason_code),
            observation_count=state.sampled_frames,
            needs_frontal_look=True,
        )
        state.last_decision = result
        return result

    def _reset_with_rejection(
        self,
        track_id: str,
        state: _TrackState,
        *,
        reason_code: str,
    ) -> TrackDecision:
        state.locked_student_id = None
        state.evidence.clear()
        result = TrackDecision(
            track_id=track_id,
            state="rejected",
            decision=RecognitionDecision(outcome="no_match", reason_code=reason_code),
            observation_count=state.sampled_frames,
        )
        state.last_decision = result
        return result

    @staticmethod
    def _collecting_decision(
        track_id: str,
        *,
        observation_count: int,
        reason_code: str,
    ) -> TrackDecision:
        return TrackDecision(
            track_id=track_id,
            state="collecting",
            decision=RecognitionDecision(outcome="retry", reason_code=reason_code),
            observation_count=observation_count,
        )
