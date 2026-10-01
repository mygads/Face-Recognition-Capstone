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
    TrackDecision,
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
    liveness_model: LivenessModel
    embedder: FaceEmbedder
    matcher: Matcher
    temporal_decision: TemporalDecisionEngine
    max_candidates: int = 2

    def __post_init__(self) -> None:
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be positive.")

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
            liveness = LivenessDecision(
                state="inconclusive",
                reason_code=code,
            )
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
                liveness = LivenessDecision(
                    state="inconclusive",
                    reason_code=_QUALITY_REJECTED,
                )
            else:
                aligned = self.aligner.align(processed, detection)
                liveness = self.liveness_model.evaluate(aligned)
                if liveness.state == "live":
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
                        confidence=liveness.confidence,
                        reason_code=_LIVENESS_REJECTED,
                    )

        return self.temporal_decision.decide(
            observation,
            matches,
            quality,
            liveness,
        )
