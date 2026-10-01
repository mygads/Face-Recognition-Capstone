from __future__ import annotations

import pytest

from recognition_core.domain import LivenessDecision
from recognition_core.liveness import LivenessConfig, apply_liveness_policy


def test_liveness_config_requires_explicit_score_when_enabled() -> None:
    with pytest.raises(ValueError, match="explicitly configured score"):
        LivenessConfig(enabled=True, required=True)
    with pytest.raises(ValueError, match="must be enabled"):
        LivenessConfig(enabled=False, required=True)


def test_live_score_at_configured_cutoff_passes() -> None:
    decision = apply_liveness_policy(
        LivenessDecision(state="live", live_score=0.75),
        LivenessConfig(enabled=True, required=True, min_live_score=0.75),
    )

    assert decision.state == "live"
    assert decision.live_score == 0.75
    assert decision.required is True
    assert decision.passed is True


def test_live_score_below_configured_cutoff_fails() -> None:
    decision = apply_liveness_policy(
        LivenessDecision(state="live", live_score=0.74),
        LivenessConfig(enabled=True, required=True, min_live_score=0.75),
    )

    assert decision.state == "spoof"
    assert decision.live_score == 0.74
    assert decision.required is True
    assert decision.passed is False
    assert decision.reason_code == "liveness_below_threshold"


def test_missing_live_score_is_inconclusive_and_cannot_pass() -> None:
    decision = apply_liveness_policy(
        LivenessDecision(state="live"),
        LivenessConfig(enabled=True, required=True, min_live_score=0.75),
    )

    assert decision.state == "inconclusive"
    assert decision.live_score is None
    assert decision.passed is False
    assert decision.reason_code == "liveness_score_missing"
