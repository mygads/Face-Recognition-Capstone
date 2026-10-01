from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from recognition_core.domain import (
    BoundingBox,
    CandidateMatch,
    FaceDetection,
    FaceEmbedding,
    FaceQuality,
    FrameObservation,
    LivenessDecision,
    RecognitionDecision,
    TrackDecision,
)
from recognition_core.liveness import LivenessConfig
from recognition_core.pipeline import RecognitionPipeline
from recognition_core.testing import (
    FakeFaceAligner,
    FakeFaceDetector,
    FakeFaceEmbedder,
    FakeFaceQualityAssessor,
    FakeLivenessModel,
    FakeMatcher,
    FakePreprocessor,
    FakeTemporalDecisionEngine,
    any_frame,
    dummy_gallery_entry,
)

TEACHER_TRACK = "track-17"
STUDENT_ID = UUID(int=77)


def test_pipeline_invokes_stages_in_order_and_delegates_temporal_decision() -> None:
    calls: list[str] = []
    face = FaceDetection(
        box=BoundingBox(10, 20, 80, 90),
        confidence=0.99,
        landmarks=((30, 45), (65, 45), (48, 60), (35, 82), (62, 82)),
    )
    quality = FaceQuality(score=0.95, acceptable=True, signals=(("blur", 0.02),))
    live = LivenessDecision(state="live", live_score=0.98)
    embedding = FaceEmbedding(
        values=(0.6, 0.8),
        model_name="fake-embedder",
        model_version="test",
        normalized=True,
    )
    match = CandidateMatch(student_id=STUDENT_ID, similarity=0.83)
    decision = TrackDecision(
        track_id=TEACHER_TRACK,
        state="accepted",
        decision=RecognitionDecision(
            outcome="matched",
            student_id=STUDENT_ID,
            confidence=0.93,
            margin=0.22,
            liveness_score=0.98,
        ),
        observation_count=3,
    )
    temporal = FakeTemporalDecisionEngine(calls, decision)
    matcher = FakeMatcher(calls, (match,))
    pipeline = RecognitionPipeline(
        preprocessor=FakePreprocessor(calls),
        detector=FakeFaceDetector(calls, (face,)),
        quality_assessor=FakeFaceQualityAssessor(calls, quality),
        aligner=FakeFaceAligner(calls),
        liveness_config=LivenessConfig(
            enabled=True,
            required=True,
            min_live_score=0.6,
        ),
        liveness_model=FakeLivenessModel(calls, live),
        embedder=FakeFaceEmbedder(calls, embedding),
        matcher=matcher,
        temporal_decision=temporal,
    )
    gallery = (dummy_gallery_entry(STUDENT_ID, embedding),)
    observation = FrameObservation(
        track_id=TEACHER_TRACK,
        captured_at=datetime.now(UTC),
    )

    result = pipeline.process(any_frame(), gallery, observation)

    assert result == decision
    assert calls == [
        "sample",
        "preprocess",
        "detect",
        "quality",
        "align",
        "liveness",
        "embed",
        "match",
        "temporal",
    ]
    assert matcher.probe == embedding
    assert matcher.gallery == gallery
    assert temporal.observation == observation
    assert temporal.matches == (match,)
    assert temporal.quality == quality
    assert temporal.liveness == LivenessDecision(
        state="live",
        live_score=0.98,
        required=True,
        passed=True,
    )


def test_quality_rejection_stops_alignment_and_embedding() -> None:
    calls: list[str] = []
    face = FaceDetection(box=BoundingBox(0, 0, 20, 20), confidence=0.9)
    quality = FaceQuality(
        score=0.2,
        acceptable=False,
        reason_codes=("face_too_small",),
    )
    decision = TrackDecision(
        track_id=TEACHER_TRACK,
        state="retry_frontal",
        decision=RecognitionDecision(outcome="retry", reason_code="face_too_small"),
        observation_count=1,
        needs_frontal_look=True,
    )
    temporal = FakeTemporalDecisionEngine(calls, decision)
    pipeline = RecognitionPipeline(
        preprocessor=FakePreprocessor(calls),
        detector=FakeFaceDetector(calls, (face,)),
        quality_assessor=FakeFaceQualityAssessor(calls, quality),
        aligner=FakeFaceAligner(calls),
        liveness_config=LivenessConfig(
            enabled=True,
            required=True,
            min_live_score=0.6,
        ),
        liveness_model=FakeLivenessModel(calls, LivenessDecision(state="live")),
        embedder=FakeFaceEmbedder(
            calls,
            FaceEmbedding((1.0,), "fake-embedder", "test", True),
        ),
        matcher=FakeMatcher(calls, ()),
        temporal_decision=temporal,
    )

    result = pipeline.process(
        any_frame(),
        (),
        FrameObservation(TEACHER_TRACK, datetime.now(UTC)),
    )

    assert result == decision
    assert calls == ["sample", "preprocess", "detect", "quality", "temporal"]
    assert temporal.quality is not None
    assert temporal.quality.reason_codes == ("face_too_small",)
    assert temporal.liveness == LivenessDecision(
        state="inconclusive",
        reason_code="quality_rejected",
        required=True,
        passed=False,
    )


def test_spoof_liveness_stops_embedding_and_matching() -> None:
    calls: list[str] = []
    face = FaceDetection(box=BoundingBox(0, 0, 30, 30), confidence=0.95)
    quality = FaceQuality(score=0.9, acceptable=True)
    spoof = LivenessDecision(state="spoof", live_score=0.01)
    decision = TrackDecision(
        track_id=TEACHER_TRACK,
        state="rejected",
        decision=RecognitionDecision(outcome="no_match", reason_code="spoof"),
        observation_count=1,
    )
    temporal = FakeTemporalDecisionEngine(calls, decision)
    pipeline = RecognitionPipeline(
        preprocessor=FakePreprocessor(calls),
        detector=FakeFaceDetector(calls, (face,)),
        quality_assessor=FakeFaceQualityAssessor(calls, quality),
        aligner=FakeFaceAligner(calls),
        liveness_config=LivenessConfig(
            enabled=True,
            required=True,
            min_live_score=0.6,
        ),
        liveness_model=FakeLivenessModel(calls, spoof),
        embedder=FakeFaceEmbedder(
            calls,
            FaceEmbedding((1.0,), "fake-embedder", "test", True),
        ),
        matcher=FakeMatcher(calls, ()),
        temporal_decision=temporal,
    )

    pipeline.process(
        any_frame(), (), FrameObservation(TEACHER_TRACK, datetime.now(UTC))
    )

    assert calls == [
        "sample",
        "preprocess",
        "detect",
        "quality",
        "align",
        "liveness",
        "temporal",
    ]
    assert temporal.liveness == LivenessDecision(
        state="spoof",
        live_score=0.01,
        reason_code="liveness_rejected",
        required=True,
        passed=False,
    )


def test_required_low_liveness_score_cannot_be_bypassed_by_temporal_engine() -> None:
    calls: list[str] = []
    face = FaceDetection(box=BoundingBox(0, 0, 30, 30), confidence=0.95)
    quality = FaceQuality(score=0.9, acceptable=True)
    accepted = TrackDecision(
        track_id=TEACHER_TRACK,
        state="accepted",
        decision=RecognitionDecision(
            outcome="matched",
            student_id=STUDENT_ID,
            confidence=0.95,
        ),
        observation_count=1,
    )
    temporal = FakeTemporalDecisionEngine(calls, accepted)
    pipeline = RecognitionPipeline(
        preprocessor=FakePreprocessor(calls),
        detector=FakeFaceDetector(calls, (face,)),
        quality_assessor=FakeFaceQualityAssessor(calls, quality),
        aligner=FakeFaceAligner(calls),
        liveness_config=LivenessConfig(
            enabled=True,
            required=True,
            min_live_score=0.75,
        ),
        liveness_model=FakeLivenessModel(
            calls,
            LivenessDecision(state="live", live_score=0.74),
        ),
        embedder=FakeFaceEmbedder(
            calls,
            FaceEmbedding((1.0,), "fake-embedder", "test", True),
        ),
        matcher=FakeMatcher(calls, ()),
        temporal_decision=temporal,
    )

    result = pipeline.process(
        any_frame(), (), FrameObservation(TEACHER_TRACK, datetime.now(UTC))
    )

    assert result.state == "rejected"
    assert result.status == "REJECTED"
    assert result.decision.outcome == "no_match"
    assert result.decision.student_id is None
    assert result.decision.liveness_score == 0.74
    assert result.decision.reason_code == "liveness_below_threshold"
    assert "embed" not in calls
    assert "match" not in calls


def test_disabled_liveness_is_explicit_and_skips_model_inference() -> None:
    calls: list[str] = []
    face = FaceDetection(box=BoundingBox(0, 0, 30, 30), confidence=0.95)
    quality = FaceQuality(score=0.9, acceptable=True)
    decision = TrackDecision(
        track_id=TEACHER_TRACK,
        state="collecting",
        decision=RecognitionDecision(outcome="retry"),
        observation_count=1,
    )
    temporal = FakeTemporalDecisionEngine(calls, decision)
    pipeline = RecognitionPipeline(
        preprocessor=FakePreprocessor(calls),
        detector=FakeFaceDetector(calls, (face,)),
        quality_assessor=FakeFaceQualityAssessor(calls, quality),
        aligner=FakeFaceAligner(calls),
        liveness_config=LivenessConfig(enabled=False, required=False),
        liveness_model=None,
        embedder=FakeFaceEmbedder(
            calls,
            FaceEmbedding((1.0,), "fake-embedder", "test", True),
        ),
        matcher=FakeMatcher(calls, ()),
        temporal_decision=temporal,
    )

    pipeline.process(
        any_frame(), (), FrameObservation(TEACHER_TRACK, datetime.now(UTC))
    )

    assert calls == [
        "sample",
        "preprocess",
        "detect",
        "quality",
        "align",
        "embed",
        "match",
        "temporal",
    ]
    assert temporal.liveness == LivenessDecision(
        state="disabled",
        reason_code="liveness_disabled",
        required=False,
    )


def test_multiple_faces_skip_quality_and_request_temporal_handling() -> None:
    calls: list[str] = []
    face = FaceDetection(box=BoundingBox(0, 0, 20, 20), confidence=0.9)
    decision = TrackDecision(
        track_id=TEACHER_TRACK,
        state="retry_frontal",
        decision=RecognitionDecision(outcome="retry", reason_code="multiple_faces"),
        observation_count=1,
        needs_frontal_look=True,
    )
    temporal = FakeTemporalDecisionEngine(calls, decision)
    pipeline = RecognitionPipeline(
        preprocessor=FakePreprocessor(calls),
        detector=FakeFaceDetector(calls, (face, face)),
        quality_assessor=FakeFaceQualityAssessor(
            calls,
            FaceQuality(score=0.9, acceptable=True),
        ),
        aligner=FakeFaceAligner(calls),
        liveness_config=LivenessConfig(
            enabled=True,
            required=True,
            min_live_score=0.6,
        ),
        liveness_model=FakeLivenessModel(calls, LivenessDecision(state="live")),
        embedder=FakeFaceEmbedder(
            calls,
            FaceEmbedding((1.0,), "fake-embedder", "test", True),
        ),
        matcher=FakeMatcher(calls, ()),
        temporal_decision=temporal,
    )

    pipeline.process(
        any_frame(), (), FrameObservation(TEACHER_TRACK, datetime.now(UTC))
    )

    assert calls == ["sample", "preprocess", "detect", "temporal"]
    assert temporal.quality is not None
    assert temporal.quality.reason_codes == ("multiple_faces",)


def test_pipeline_sampling_skips_before_preprocess_and_model_work() -> None:
    calls: list[str] = []
    decision = TrackDecision(
        track_id=TEACHER_TRACK,
        state="collecting",
        decision=RecognitionDecision(outcome="retry", reason_code="awaiting_consensus"),
        observation_count=0,
    )
    temporal = FakeTemporalDecisionEngine(calls, decision)
    temporal.sample_result = False
    pipeline = RecognitionPipeline(
        preprocessor=FakePreprocessor(calls),
        detector=FakeFaceDetector(calls, ()),
        quality_assessor=FakeFaceQualityAssessor(
            calls,
            FaceQuality(score=0.9, acceptable=True),
        ),
        aligner=FakeFaceAligner(calls),
        liveness_config=LivenessConfig(
            enabled=True,
            required=True,
            min_live_score=0.6,
        ),
        liveness_model=FakeLivenessModel(calls, LivenessDecision(state="live")),
        embedder=FakeFaceEmbedder(
            calls,
            FaceEmbedding((1.0,), "fake-embedder", "test", True),
        ),
        matcher=FakeMatcher(calls, ()),
        temporal_decision=temporal,
    )

    result = pipeline.process(
        any_frame(), (), FrameObservation(TEACHER_TRACK, datetime.now(UTC))
    )

    assert result == decision
    assert calls == ["sample", "skip"]
