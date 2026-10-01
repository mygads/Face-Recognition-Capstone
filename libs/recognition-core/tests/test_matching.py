from __future__ import annotations

from uuid import UUID

import pytest

from recognition_core.domain import FaceEmbedding, GalleryEntry
from recognition_core.evaluation import evaluate_pairs
from recognition_core.matching import CosineSimilarityMatcher, cosine_similarity


def _embedding(values: tuple[float, ...], version: str = "sface-test") -> FaceEmbedding:
    return FaceEmbedding(
        values=values,
        model_name="synthetic",
        model_version=version,
        normalized=False,
    )


def test_cosine_similarity_and_matcher_leave_threshold_unset_by_default() -> None:
    probe = _embedding((3.0, 4.0))
    aligned = _embedding((6.0, 8.0))
    orthogonal = _embedding((1.0, 0.0))

    assert cosine_similarity(probe, aligned) == pytest.approx(1.0)
    assert cosine_similarity(probe, orthogonal) == pytest.approx(0.6)
    matcher = CosineSimilarityMatcher()
    assert matcher.minimum_similarity is None
    assert matcher.passes_threshold(0.99) is None
    results = matcher.match(
        probe,
        [
            GalleryEntry(UUID(int=1), orthogonal),
            GalleryEntry(UUID(int=2), aligned),
        ],
    )
    assert [candidate.student_id for candidate in results] == [UUID(int=2), UUID(int=1)]


def test_cosine_matcher_accepts_explicit_calibration_threshold_only() -> None:
    matcher = CosineSimilarityMatcher(minimum_similarity=0.75)
    assert matcher.passes_threshold(0.8) is True
    assert matcher.passes_threshold(0.7) is False
    with pytest.raises(ValueError, match="between -1 and 1"):
        CosineSimilarityMatcher(minimum_similarity=1.1)


def test_cosine_similarity_rejects_incompatible_model_and_dimensions() -> None:
    with pytest.raises(ValueError, match="different model versions"):
        cosine_similarity(_embedding((1.0, 0.0)), _embedding((1.0, 0.0), "other"))
    with pytest.raises(ValueError, match="different dimensions"):
        cosine_similarity(_embedding((1.0, 0.0)), _embedding((1.0,)))


def test_folder_evaluation_reports_score_summaries_without_threshold() -> None:
    summary = evaluate_pairs(
        {
            "synthetic-group-a": [_embedding((1.0, 0.0)), _embedding((1.0, 0.0))],
            "synthetic-group-b": [_embedding((0.0, 1.0)), _embedding((0.0, 1.0))],
        }
    )

    assert summary.threshold is None
    assert summary.same_identity.count == 2
    assert summary.same_identity.mean == pytest.approx(1.0)
    assert summary.different_identity.count == 4
    assert summary.different_identity.mean == pytest.approx(0.0)
    assert summary.different_identity.acceptance_rate is None


def test_folder_evaluation_uses_only_explicit_threshold_for_pair_rates() -> None:
    summary = evaluate_pairs(
        {
            "a": [_embedding((1.0, 0.0)), _embedding((1.0, 0.0))],
            "b": [_embedding((0.0, 1.0))],
        },
        threshold=0.8,
    )

    assert summary.same_identity.acceptance_rate == 1.0
    assert summary.different_identity.acceptance_rate == 0.0
    with pytest.raises(ValueError, match="between -1 and 1"):
        evaluate_pairs({}, threshold=float("nan"))
