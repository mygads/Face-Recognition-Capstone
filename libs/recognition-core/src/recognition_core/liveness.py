"""Configurable anti-spoof policy around replaceable liveness models."""

from __future__ import annotations

import math
from dataclasses import dataclass

from recognition_core.domain import LivenessDecision


@dataclass(frozen=True, slots=True)
class LivenessConfig:
    """Runtime policy; score cutoffs must be calibrated for each deployment."""

    enabled: bool
    required: bool
    min_live_score: float | None = None

    def __post_init__(self) -> None:
        if self.required and not self.enabled:
            raise ValueError("Required liveness must be enabled.")
        if self.enabled and self.min_live_score is None:
            raise ValueError("Enabled liveness needs an explicitly configured score.")
        if self.min_live_score is not None and (
            not math.isfinite(self.min_live_score) or not 0 <= self.min_live_score <= 1
        ):
            raise ValueError("min_live_score must be finite and between 0 and 1.")


def apply_liveness_policy(
    model_result: LivenessDecision,
    config: LivenessConfig,
) -> LivenessDecision:
    """Apply configured live-score threshold and required/optional policy."""
    if not config.enabled:
        return LivenessDecision(
            state="disabled",
            reason_code="liveness_disabled",
            required=False,
        )

    live_score = model_result.live_score
    minimum_score = config.min_live_score
    passed = (
        model_result.state == "live"
        and live_score is not None
        and minimum_score is not None
        and live_score >= minimum_score
    )
    state = model_result.state
    reason_code = model_result.reason_code
    if model_result.state == "live" and live_score is None:
        state = "inconclusive"
        reason_code = reason_code or "liveness_score_missing"
    elif model_result.state == "live" and not passed:
        state = "spoof"
        reason_code = reason_code or "liveness_below_threshold"

    return LivenessDecision(
        state=state,
        live_score=live_score,
        reason_code=reason_code,
        required=config.required,
        passed=passed,
    )


def liveness_not_evaluated(
    config: LivenessConfig,
    *,
    reason_code: str,
) -> LivenessDecision:
    """Represent frames that cannot safely reach the liveness model."""
    return LivenessDecision(
        state="inconclusive",
        reason_code=reason_code,
        required=config.required,
        passed=False if config.required else None,
    )
