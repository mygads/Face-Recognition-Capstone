"""Cosine similarity baseline without a built-in acceptance policy."""

from __future__ import annotations

import importlib
import math
from collections.abc import Sequence
from typing import Any

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
        try:
            self._numpy: Any | None = importlib.import_module("numpy")
        except ImportError:
            self._numpy = None

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
        if not gallery:
            return ()
        if self._numpy is None:
            candidates = [
                CandidateMatch(
                    student_id=entry.student_id,
                    similarity=cosine_similarity(probe, entry.embedding),
                )
                for entry in gallery
            ]
        else:
            candidates = self._match_with_numpy(probe, gallery)
        return tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    -candidate.similarity,
                    str(candidate.student_id),
                ),
            )[:limit]
        )

    def _match_with_numpy(
        self,
        probe: FaceEmbedding,
        gallery: Sequence[GalleryEntry],
    ) -> list[CandidateMatch]:
        numpy = self._numpy
        assert numpy is not None
        for entry in gallery:
            if (
                probe.model_name != entry.embedding.model_name
                or probe.model_version != entry.embedding.model_version
            ):
                raise ValueError(
                    "Cannot compare embeddings produced by different model versions."
                )
            if len(probe.values) != len(entry.embedding.values):
                raise ValueError("Cannot compare embeddings with different dimensions.")

        probe_values = numpy.asarray(probe.values, dtype=numpy.float64)
        probe_norm = float(numpy.linalg.norm(probe_values))
        if probe_norm <= 0:
            raise ValueError("Cannot compare a zero-length embedding.")
        gallery_values = numpy.asarray(
            [entry.embedding.values for entry in gallery],
            dtype=numpy.float64,
        )
        gallery_norms = numpy.linalg.norm(gallery_values, axis=1)
        if bool(numpy.any(gallery_norms <= 0)):
            raise ValueError("Cannot compare a zero-length embedding.")
        similarities = (gallery_values @ probe_values) / (gallery_norms * probe_norm)
        return [
            CandidateMatch(
                student_id=entry.student_id,
                similarity=max(-1.0, min(1.0, float(similarity))),
            )
            for entry, similarity in zip(gallery, similarities, strict=True)
        ]
