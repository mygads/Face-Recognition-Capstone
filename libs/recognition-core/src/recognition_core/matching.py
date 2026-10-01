"""Cosine similarity baseline without a built-in acceptance policy."""

from __future__ import annotations

import math
from collections.abc import Sequence

from recognition_core.domain import CandidateMatch, FaceEmbedding, GalleryEntry
from recognition_core.protocols import Matcher


def cosine_similarity(left: FaceEmbedding, right: FaceEmbedding) -> float:
    """Return cosine similarity after checking embedding compatibility."""
    if left.model_name != right.model_name or left.model_version != right.model_version:
        raise ValueError(
            "Cannot compare embeddings produced by different model versions."
        )
    if len(left.values) != len(right.values):
        raise ValueError("Cannot compare embeddings with different dimensions.")
    left_norm = math.sqrt(sum(value * value for value in left.values))
    right_norm = math.sqrt(sum(value * value for value in right.values))
    if left_norm <= 0 or right_norm <= 0:
        raise ValueError("Cannot compare a zero-length embedding.")
    score = sum(a * b for a, b in zip(left.values, right.values, strict=True)) / (
        left_norm * right_norm
    )
    return max(-1.0, min(1.0, score))


class CosineSimilarityMatcher(Matcher):
    """Rank compatible gallery embeddings by cosine score.

    ``minimum_similarity`` is optional and never filters candidate results. It is
    only available to downstream policy as an explicitly configured calibration
    value; when omitted, the matcher reports similarity without a decision.
    """

    def __init__(self, minimum_similarity: float | None = None) -> None:
        if minimum_similarity is not None and (
            not math.isfinite(minimum_similarity) or not -1 <= minimum_similarity <= 1
        ):
            raise ValueError("minimum_similarity must be between -1 and 1.")
        self.minimum_similarity = minimum_similarity

    def passes_threshold(self, similarity: float) -> bool | None:
        if self.minimum_similarity is None:
            return None
        if not math.isfinite(similarity) or not -1 <= similarity <= 1:
            raise ValueError("similarity must be between -1 and 1.")
        return similarity >= self.minimum_similarity

    def match(
        self,
        probe: FaceEmbedding,
        gallery: Sequence[GalleryEntry],
        *,
        limit: int = 2,
    ) -> tuple[CandidateMatch, ...]:
        if limit < 1:
            raise ValueError("limit must be positive.")
        candidates = (
            CandidateMatch(
                student_id=entry.student_id,
                similarity=cosine_similarity(probe, entry.embedding),
            )
            for entry in gallery
        )
        return tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    -candidate.similarity,
                    str(candidate.student_id),
                ),
            )[:limit]
        )
