from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from recognition_core.domain import TrackDecision

RecognitionOutcome = Literal["matched", "ambiguous", "no_match", "error"]


def event_payload(
    decision: TrackDecision,
    *,
    device_id: UUID,
    session_id: UUID,
    occurred_at: datetime,
    model_name: str,
    model_version: str,
    liveness_required: bool,
    liveness_enabled: bool,
    min_live_score: float | None,
) -> dict[str, object]:
    result = decision.decision
    if result.outcome == "matched":
        outcome: RecognitionOutcome = "matched"
    elif result.outcome == "ambiguous" or decision.state == "retry_frontal":
        outcome = "ambiguous"
    elif result.outcome == "error":
        outcome = "error"
    else:
        outcome = "no_match"

    liveness_passed: bool | None = None
    if liveness_required and outcome == "matched":
        liveness_passed = True
    elif (
        liveness_enabled
        and result.liveness_score is not None
        and min_live_score is not None
    ):
        liveness_passed = result.liveness_score >= min_live_score
    elif result.reason_code is not None and (
        result.reason_code.startswith("liveness") or result.reason_code == "spoof"
    ):
        liveness_passed = False

    confidence = result.confidence
    similarity = (
        max(-1.0, min(1.0, confidence * 2.0 - 1.0))
        if outcome == "matched" and confidence is not None
        else None
    )
    margin = result.margin if outcome == "matched" else None
    return {
        "event_id": str(uuid4()),
        "device_id": str(device_id),
        "session_id": str(session_id),
        "student_id": str(result.student_id) if outcome == "matched" else None,
        "outcome": outcome,
        "similarity": similarity,
        "confidence": confidence if outcome == "matched" else None,
        "margin": margin,
        "liveness_passed": liveness_passed,
        "liveness_score": result.liveness_score,
        "occurred_at": occurred_at.isoformat(),
        "model_name": model_name,
        "model_version": model_version,
    }
