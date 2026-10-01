from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from uuid import UUID


class AIServiceConfigError(ValueError):
    """Raised when service configuration is malformed or unsafe."""


@dataclass(frozen=True, slots=True)
class AISettings:
    device_tokens: Mapping[UUID, str] = field(default_factory=dict, repr=False)
    core_api_base_url: str | None = None
    max_request_bytes: int = 20 * 1024 * 1024
    max_frame_bytes: int = 3 * 1024 * 1024
    max_frames_per_burst: int = 5
    max_image_width: int = 4096
    max_image_height: int = 4096
    max_image_pixels: int = 16_000_000
    inference_timeout_seconds: float = 5.0
    rate_limit_per_second: float = 10.0
    rate_limit_burst: int = 20
    gallery_max_age_seconds: float = 300.0
    yunet_model_path: Path | None = None
    sface_model_path: Path | None = None
    model_version: str | None = None
    min_top1_similarity: float | None = None
    min_top1_top2_margin: float | None = None
    minimum_agreeing_frames: int = 3
    sample_every_n_frames: int = 2
    best_frame_count: int = 5
    max_history_frames: int = 10
    min_face_pixels: int = 80
    min_laplacian_variance: float = 45.0
    min_brightness: float = 25.0
    max_brightness: float = 235.0
    liveness_enabled: bool = False
    liveness_required: bool = False
    liveness_min_score: float | None = None
    liveness_model_path: Path | None = None
    liveness_model_version: str | None = None
    benchmark_timing_enabled: bool = False

    def __post_init__(self) -> None:
        positive_ints = (
            ("max_request_bytes", self.max_request_bytes),
            ("max_frame_bytes", self.max_frame_bytes),
            ("max_frames_per_burst", self.max_frames_per_burst),
            ("max_image_width", self.max_image_width),
            ("max_image_height", self.max_image_height),
            ("max_image_pixels", self.max_image_pixels),
            ("rate_limit_burst", self.rate_limit_burst),
            ("minimum_agreeing_frames", self.minimum_agreeing_frames),
            ("sample_every_n_frames", self.sample_every_n_frames),
            ("best_frame_count", self.best_frame_count),
            ("max_history_frames", self.max_history_frames),
            ("min_face_pixels", self.min_face_pixels),
        )
        for name, count in positive_ints:
            if count < 1:
                raise AIServiceConfigError(f"{name} must be positive.")
        for name, number in (
            ("inference_timeout_seconds", self.inference_timeout_seconds),
            ("rate_limit_per_second", self.rate_limit_per_second),
            ("gallery_max_age_seconds", self.gallery_max_age_seconds),
        ):
            if not math.isfinite(number) or number <= 0:
                raise AIServiceConfigError(f"{name} must be finite and positive.")
        if self.max_request_bytes < self.max_frame_bytes:
            raise AIServiceConfigError("Request limit must cover at least one frame.")
        if self.max_history_frames < self.best_frame_count:
            raise AIServiceConfigError(
                "max_history_frames must cover best_frame_count."
            )
        if self.best_frame_count < self.minimum_agreeing_frames:
            raise AIServiceConfigError(
                "best_frame_count must cover minimum_agreeing_frames."
            )
        if self.min_brightness >= self.max_brightness:
            raise AIServiceConfigError("min_brightness must be below max_brightness.")
        for name, optional_score, low, high in (
            ("min_top1_similarity", self.min_top1_similarity, -1.0, 1.0),
            ("min_top1_top2_margin", self.min_top1_top2_margin, 0.0, 2.0),
            ("liveness_min_score", self.liveness_min_score, 0.0, 1.0),
        ):
            if optional_score is not None and (
                not math.isfinite(optional_score) or not low <= optional_score <= high
            ):
                raise AIServiceConfigError(f"{name} is outside its valid range.")
        if self.liveness_required and not self.liveness_enabled:
            raise AIServiceConfigError("Required liveness must be enabled.")
        if self.liveness_enabled and (
            self.liveness_min_score is None
            or self.liveness_model_path is None
            or self.liveness_model_version is None
        ):
            raise AIServiceConfigError(
                "Enabled liveness needs an audited local model, version, "
                "and calibrated score."
            )
        if self.core_api_base_url is not None and not self.core_api_base_url.startswith(
            ("http://", "https://")
        ):
            raise AIServiceConfigError("Core API URL must use http:// or https://.")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> AISettings:
        values = os.environ if environ is None else environ
        tokens: dict[UUID, str] = {}
        raw_tokens = values.get("PRESENSI_AI_DEVICE_TOKENS", "").strip()
        if raw_tokens:
            try:
                parsed = json.loads(raw_tokens)
            except json.JSONDecodeError as exc:
                raise AIServiceConfigError(
                    "PRESENSI_AI_DEVICE_TOKENS must be a JSON object."
                ) from exc
            if not isinstance(parsed, dict):
                raise AIServiceConfigError(
                    "PRESENSI_AI_DEVICE_TOKENS must be a JSON object."
                )
            for raw_device_id, token in parsed.items():
                try:
                    device_id = UUID(raw_device_id)
                except (TypeError, ValueError) as exc:
                    raise AIServiceConfigError(
                        "Device token map contains an invalid device UUID."
                    ) from exc
                if not isinstance(token, str) or len(token) < 32 or not token.isascii():
                    raise AIServiceConfigError(
                        "Each configured device token must be 32+ ASCII characters."
                    )
                tokens[device_id] = token

        def int_setting(name: str, default: int) -> int:
            raw = values.get(name)
            if raw is None or raw == "":
                return default
            try:
                return int(raw)
            except ValueError as exc:
                raise AIServiceConfigError(f"Invalid integer for {name}.") from exc

        def float_setting(name: str, default: float | None = None) -> float | None:
            raw = values.get(name)
            if raw is None or raw.strip() == "":
                return default
            try:
                result = float(raw)
            except ValueError as exc:
                raise AIServiceConfigError(f"Invalid number for {name}.") from exc
            if not math.isfinite(result):
                raise AIServiceConfigError(f"Invalid number for {name}.")
            return result

        def float_with_default(name: str, default: float) -> float:
            result = float_setting(name, default)
            assert result is not None
            return result

        def bool_setting(name: str, default: bool = False) -> bool:
            raw = values.get(name)
            if raw is None or raw == "":
                return default
            normalized = raw.strip().lower()
            if normalized in {"true", "1", "yes"}:
                return True
            if normalized in {"false", "0", "no"}:
                return False
            raise AIServiceConfigError(f"Invalid boolean for {name}.")

        def path_setting(name: str) -> Path | None:
            raw = values.get(name, "").strip()
            return Path(raw).expanduser() if raw else None

        return cls(
            device_tokens=tokens,
            core_api_base_url=(
                values.get("PRESENSI_AI_CORE_API_BASE_URL", "").strip().rstrip("/")
                or None
            ),
            max_request_bytes=int_setting(
                "PRESENSI_AI_MAX_REQUEST_BYTES", 20 * 1024 * 1024
            ),
            max_frame_bytes=int_setting("PRESENSI_AI_MAX_FRAME_BYTES", 3 * 1024 * 1024),
            max_frames_per_burst=int_setting("PRESENSI_AI_MAX_FRAMES", 5),
            max_image_width=int_setting("PRESENSI_AI_MAX_IMAGE_WIDTH", 4096),
            max_image_height=int_setting("PRESENSI_AI_MAX_IMAGE_HEIGHT", 4096),
            max_image_pixels=int_setting("PRESENSI_AI_MAX_IMAGE_PIXELS", 16_000_000),
            inference_timeout_seconds=float_with_default(
                "PRESENSI_AI_INFERENCE_TIMEOUT_SECONDS", 5.0
            ),
            rate_limit_per_second=float_with_default(
                "PRESENSI_AI_RATE_LIMIT_PER_SECOND", 10.0
            ),
            rate_limit_burst=int_setting("PRESENSI_AI_RATE_LIMIT_BURST", 20),
            gallery_max_age_seconds=float_with_default(
                "PRESENSI_AI_GALLERY_MAX_AGE_SECONDS", 300.0
            ),
            yunet_model_path=path_setting("PRESENSI_AI_YUNET_MODEL_PATH"),
            sface_model_path=path_setting("PRESENSI_AI_SFACE_MODEL_PATH"),
            model_version=values.get("PRESENSI_AI_MODEL_VERSION") or None,
            min_top1_similarity=float_setting("PRESENSI_AI_MIN_TOP1_SIMILARITY"),
            min_top1_top2_margin=float_setting("PRESENSI_AI_MIN_TOP1_TOP2_MARGIN"),
            minimum_agreeing_frames=int_setting(
                "PRESENSI_AI_MINIMUM_AGREEING_FRAMES", 3
            ),
            sample_every_n_frames=int_setting("PRESENSI_AI_SAMPLE_EVERY_N_FRAMES", 1),
            best_frame_count=int_setting("PRESENSI_AI_BEST_FRAME_COUNT", 5),
            max_history_frames=int_setting("PRESENSI_AI_MAX_HISTORY_FRAMES", 10),
            min_face_pixels=int_setting("PRESENSI_AI_MIN_FACE_PIXELS", 80),
            min_laplacian_variance=float_with_default(
                "PRESENSI_AI_MIN_LAPLACIAN_VARIANCE", 45.0
            ),
            min_brightness=float_with_default("PRESENSI_AI_MIN_BRIGHTNESS", 25.0),
            max_brightness=float_with_default("PRESENSI_AI_MAX_BRIGHTNESS", 235.0),
            liveness_enabled=bool_setting("PRESENSI_AI_LIVENESS_ENABLED"),
            liveness_required=bool_setting("PRESENSI_AI_LIVENESS_REQUIRED"),
            liveness_min_score=float_setting("PRESENSI_AI_LIVENESS_MIN_SCORE"),
            liveness_model_path=path_setting("PRESENSI_AI_LIVENESS_MODEL_PATH"),
            liveness_model_version=values.get("PRESENSI_AI_LIVENESS_MODEL_VERSION")
            or None,
            benchmark_timing_enabled=bool_setting(
                "PRESENSI_AI_BENCHMARK_TIMING_ENABLED"
            ),
        )
