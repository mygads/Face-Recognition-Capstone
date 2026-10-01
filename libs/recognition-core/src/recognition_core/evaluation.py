"""Pairwise score summaries for local, labelled image-folder benchmarks."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from recognition_core.domain import FaceEmbedding
from recognition_core.matching import cosine_similarity


@dataclass(frozen=True, slots=True)
class ScoreSummary:
    count: int
    mean: float | None
    minimum: float | None
    maximum: float | None
    accepted_count: int | None

    @property
    def acceptance_rate(self) -> float | None:
        if self.count == 0 or self.accepted_count is None:
            return None
        return self.accepted_count / self.count


@dataclass(frozen=True, slots=True)
class BenchmarkSummary:
    threshold: float | None
    same_identity: ScoreSummary
    different_identity: ScoreSummary


def evaluate_pairs(
    groups: Mapping[str, Sequence[FaceEmbedding]],
    *,
    threshold: float | None = None,
) -> BenchmarkSummary:
    """Evaluate every within-label and cross-label pair, without naming labels."""
    if threshold is not None and (
        not math.isfinite(threshold) or not -1 <= threshold <= 1
    ):
        raise ValueError("threshold must be between -1 and 1.")

    same: list[float] = []
    different: list[float] = []
    labels = sorted(groups)
    for label in labels:
        embeddings = groups[label]
        for left_index, left in enumerate(embeddings):
            for right in embeddings[left_index + 1 :]:
                same.append(cosine_similarity(left, right))
    for label_index, label in enumerate(labels):
        for other_label in labels[label_index + 1 :]:
            for left in groups[label]:
                for right in groups[other_label]:
                    different.append(cosine_similarity(left, right))

    return BenchmarkSummary(
        threshold=threshold,
        same_identity=_summarize(same, threshold),
        different_identity=_summarize(different, threshold),
    )


def _summarize(scores: Sequence[float], threshold: float | None) -> ScoreSummary:
    accepted_count = (
        sum(score >= threshold for score in scores) if threshold is not None else None
    )
    if not scores:
        return ScoreSummary(0, None, None, None, accepted_count)
    return ScoreSummary(
        count=len(scores),
        mean=sum(scores) / len(scores),
        minimum=min(scores),
        maximum=max(scores),
        accepted_count=accepted_count,
    )
