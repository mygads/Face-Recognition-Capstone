from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from recognition_core.domain import (
    CandidateMatch,
    FaceQuality,
    FrameObservation,
    GalleryEntry,
    LivenessDecision,
    RecognitionDecision,
    TrackDecision,
)
from recognition_core.liveness import (
    LivenessConfig,
    apply_liveness_policy,
    liveness_not_evaluated,
)
from recognition_core.protocols import (
    FaceAligner,
    FaceDetector,
    FaceEmbedder,
    FaceQualityAssessor,
    ImageFrame,
    LivenessModel,
    Matcher,
    Preprocessor,
    TemporalDecisionEngine,
)

_NO_DETECTION: Final = "no_face"
_MULTIPLE_DETECTIONS: Final = "multiple_faces"
_QUALITY_REJECTED: Final = "quality_rejected"
_LIVENESS_REJECTED: Final = "liveness_rejected"


@dataclass(slots=True)
class RecognitionPipeline:
    preprocessor: Preprocessor
    detector: FaceDetector
    quality_assessor: FaceQualityAssessor
    aligner: FaceAligner
    liveness_config: LivenessConfig
    liveness_model: LivenessModel | None
    embedder: FaceEmbedder
    matcher: Matcher
    temporal_decision: TemporalDecisionEngine
    max_candidates: int = 2

    def __post_init__(self) -> None:
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be positive.")
        if self.liveness_config.enabled and self.liveness_model is None:
            raise ValueError("Enabled liveness requires a configured model.")

    def process(
        self,
        frame: ImageFrame,
        gallery: Sequence[GalleryEntry],
        observation: FrameObservation,
    ) -> TrackDecision:
        if not self.temporal_decision.should_sample(observation):
            return self.temporal_decision.on_skipped(observation)

        processed = self.preprocessor.preprocess(frame)
        detections = self.detector.detect(processed)
        matches: tuple[CandidateMatch, ...] = ()

        if len(detections) != 1:
            code = _NO_DETECTION if not detections else _MULTIPLE_DETECTIONS
            quality = FaceQuality(
                score=0.0,
                acceptable=False,
                reason_codes=(code,),
            )
            liveness = liveness_not_evaluated(self.liveness_config, reason_code=code)
        else:
            detection = detections[0]
            quality = self.quality_assessor.assess(processed, detection)
            if not quality.acceptable:
                quality = FaceQuality(
                    score=quality.score,
                    acceptable=False,
                    signals=quality.signals,
                    reason_codes=quality.reason_codes or (_QUALITY_REJECTED,),
                )
                liveness = liveness_not_evaluated(
                    self.liveness_config,
                    reason_code=_QUALITY_REJECTED,
                )
            else:
                aligned = self.aligner.align(processed, detection)
                if self.liveness_config.enabled:
                    assert self.liveness_model is not None
                    model_result = self.liveness_model.evaluate(aligned)
                    liveness = apply_liveness_policy(
                        model_result,
                        self.liveness_config,
                    )
                else:
                    liveness = apply_liveness_policy(
                        LivenessDecision(state="inconclusive"),
                        self.liveness_config,
                    )

                if not liveness.required or liveness.passed is True:
                    probe = self.embedder.embed(aligned)
                    matches = tuple(
                        self.matcher.match(
                            probe,
                            gallery,
                            limit=self.max_candidates,
                        )
                    )
                elif liveness.reason_code is None:
                    liveness = LivenessDecision(
                        state=liveness.state,
                        live_score=liveness.live_score,
                        reason_code=_LIVENESS_REJECTED,
                        required=liveness.required,
                        passed=liveness.passed,
                    )

        decision = self.temporal_decision.decide(
            observation,
            matches,
            quality,
            liveness,
        )
        if liveness.required and liveness.passed is not True:
            return self._prevent_required_liveness_bypass(decision, liveness)
        return decision

    @staticmethod
    def _prevent_required_liveness_bypass(
        decision: TrackDecision,
        liveness: LivenessDecision,
    ) -> TrackDecision:
        """Fail closed if a custom temporal engine returns accept on failed PAD."""
        if decision.state != "accepted":
            return decision
        if liveness.state == "spoof":
            return TrackDecision(
                track_id=decision.track_id,
                state="rejected",
                decision=RecognitionDecision(
                    outcome="no_match",
                    liveness_score=liveness.live_score,
                    reason_code=liveness.reason_code or _LIVENESS_REJECTED,
                ),
                observation_count=decision.observation_count,
            )
        return TrackDecision(
            track_id=decision.track_id,
            state="retry_frontal",
            decision=RecognitionDecision(
                outcome="retry",
                liveness_score=liveness.live_score,
                reason_code=liveness.reason_code or "liveness_inconclusive",
            ),
            observation_count=decision.observation_count,
            needs_frontal_look=True,
        )
