from __future__ import annotations

import base64
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx

from presensi_edge_agent.api import ApiCallError
from presensi_edge_agent.config import CentralAISettings

MAX_JPEG_BYTES = 1_048_576


@dataclass(frozen=True, slots=True)
class BurstFrame:
    image: bytes
    captured_at: datetime


@dataclass(frozen=True, slots=True)
class CentralDecision:
    session_id: UUID
    track_id: str
    outcome: str
    student_id: UUID | None
    confidence: float | None
    margin: float | None
    reason_code: str | None
    liveness_score: float | None
    model_version: str


class CentralAIClient:
    """Small trusted-device client; image bytes exist only in the request body."""

    def __init__(
        self,
        settings: CentralAISettings,
        device_id: UUID,
        token_provider: Callable[[], str | None],
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self.device_id = device_id
        self._token_provider = token_provider
        self._client = client or httpx.Client(
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
            follow_redirects=False,
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def health(self) -> bool:
        try:
            response = self._client.get("/health")
        except httpx.RequestError:
            return False
        return response.status_code < 400

    def recognize_burst(
        self,
        *,
        session_id: UUID,
        track_id: str,
        frames: Sequence[BurstFrame],
    ) -> CentralDecision:
        if not frames or len(frames) > 5:
            raise ValueError("A recognition burst must contain 1 to 5 frames.")
        encoded_frames: list[dict[str, str]] = []
        previous_timestamp: datetime | None = None
        for frame in frames:
            if not frame.captured_at.tzinfo or frame.captured_at.utcoffset() is None:
                raise ValueError("Captured frame timestamps must be timezone-aware.")
            if (
                previous_timestamp is not None
                and frame.captured_at <= previous_timestamp
            ):
                raise ValueError("Captured frame timestamps must be strictly ordered.")
            if len(frame.image) > MAX_JPEG_BYTES:
                raise ValueError("Encoded camera frame exceeds the gateway limit.")
            previous_timestamp = frame.captured_at
            encoded_frames.append(
                {
                    "captured_at": frame.captured_at.isoformat(),
                    "content_type": "image/jpeg",
                    "image_base64": base64.b64encode(frame.image).decode("ascii"),
                }
            )

        token = self._token_provider()
        if not token:
            raise ApiCallError(401, retryable=True)
        try:
            response = self._client.post(
                f"/api/v1/recognition/sessions/{session_id}/bursts",
                json={"track_id": track_id, "frames": encoded_frames},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Device-ID": str(self.device_id),
                },
            )
        except httpx.TimeoutException as exc:
            raise ApiCallError(None, retryable=True) from exc
        except httpx.RequestError as exc:
            raise ApiCallError(None, retryable=True) from exc
        if response.status_code >= 400:
            status_code = response.status_code
            retryable = status_code in {401, 403, 408, 425, 429} or status_code >= 500
            raise ApiCallError(status_code, retryable=retryable)
        try:
            payload = response.json()
            decision = _parse_decision(
                payload, requested_session=session_id, requested_track=track_id
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise ApiCallError(response.status_code, retryable=False) from exc
        return decision


def _parse_decision(
    value: Any, *, requested_session: UUID, requested_track: str
) -> CentralDecision:
    if not isinstance(value, dict):
        raise ValueError("Central AI response must be an object.")
    session_id = UUID(str(value["session_id"]))
    if session_id != requested_session:
        raise ValueError("Central AI response session does not match the request.")
    track_id = value["track_id"]
    outcome = value["outcome"]
    model_version = value["model_version"]
    candidate = value.get("candidate")
    if not isinstance(track_id, str) or not track_id:
        raise ValueError("Central AI response is missing a track id.")
    if track_id != requested_track:
        raise ValueError("Central AI response track does not match the request.")
    if outcome not in {"matched", "ambiguous", "no_match", "error"}:
        raise ValueError("Central AI response contains an unknown outcome.")
    if (
        not isinstance(model_version, str)
        or not model_version.strip()
        or len(model_version) > 80
    ):
        raise ValueError("Central AI response is missing the model version.")
    if candidate is not None and not isinstance(candidate, dict):
        raise ValueError("Central AI candidate metadata is invalid.")
    student_id: UUID | None = None
    confidence: float | None = None
    margin: float | None = None
    if candidate is not None:
        student_id = UUID(str(candidate["student_id"]))
        confidence = _optional_unit_interval(candidate.get("confidence"), "confidence")
        margin = _optional_bounded(candidate.get("margin"), "margin", upper=2.0)
    if outcome == "matched" and (student_id is None or confidence is None):
        raise ValueError("Matched response requires candidate confidence.")
    reason_code = value.get("reason_code")
    if reason_code is not None and not isinstance(reason_code, str):
        raise ValueError("Central AI reason code is invalid.")
    return CentralDecision(
        session_id=session_id,
        track_id=track_id,
        outcome=outcome,
        student_id=student_id,
        confidence=confidence,
        margin=margin,
        reason_code=reason_code,
        liveness_score=_optional_bounded(
            value.get("liveness_score"), "liveness_score", upper=1.0
        ),
        model_version=model_version,
    )


def _optional_unit_interval(value: Any, name: str) -> float | None:
    return _optional_bounded(value, name, upper=1.0)


def _optional_bounded(value: Any, name: str, *, upper: float) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Central AI {name} must be numeric.")
    parsed = float(value)
    if not 0 <= parsed <= upper:
        raise ValueError(f"Central AI {name} must be between 0 and {upper:g}.")
    return parsed
