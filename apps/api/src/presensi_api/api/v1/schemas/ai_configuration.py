from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from presensi_api.api.v1.schemas.common import ApiSchema


class FaceQualityConfiguration(ApiSchema):
    min_face_pixels: int = Field(ge=16, le=2048)
    min_laplacian_variance: float = Field(ge=0, le=100_000)
    min_brightness: float = Field(ge=0, le=254)
    max_brightness: float = Field(ge=1, le=255)

    @model_validator(mode="after")
    def validate_brightness_range(self) -> Self:
        if self.min_brightness >= self.max_brightness:
            raise ValueError("Brightness minimum must be below maximum.")
        return self


class EnrollmentQualityConfiguration(ApiSchema):
    min_face_pixels: int = Field(ge=16, le=2048)
    min_sharpness: float = Field(ge=0, le=100_000)
    min_brightness: float = Field(ge=0, le=254)
    max_brightness: float = Field(ge=1, le=255)

    @model_validator(mode="after")
    def validate_brightness_range(self) -> Self:
        if self.min_brightness >= self.max_brightness:
            raise ValueError("Brightness minimum must be below maximum.")
        return self


class RecognitionConfiguration(FaceQualityConfiguration):
    min_top1_similarity: float | None = Field(default=None, ge=-1, le=1)
    min_top1_top2_margin: float | None = Field(default=None, ge=0, le=2)
    minimum_agreeing_frames: int = Field(ge=1, le=10)
    sample_every_n_frames: int = Field(ge=1, le=60)
    best_frame_count: int = Field(ge=1, le=20)
    max_history_frames: int = Field(ge=1, le=60)
    calibration_reference: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_recognition_policy(self) -> Self:
        thresholds_present = (
            self.min_top1_similarity is not None
            and self.min_top1_top2_margin is not None
        )
        if (self.min_top1_similarity is None) != (self.min_top1_top2_margin is None):
            raise ValueError("Top-1 and margin thresholds must be configured together.")
        if thresholds_present and not (self.calibration_reference or "").strip():
            raise ValueError(
                "Provide the calibration report reference before saving thresholds."
            )
        if self.best_frame_count < self.minimum_agreeing_frames:
            raise ValueError("Best frame count must cover agreeing frame count.")
        if self.max_history_frames < self.best_frame_count:
            raise ValueError("History frame count must cover best frame count.")
        return self


class StbGatewayConfiguration(ApiSchema):
    motion_threshold: float = Field(ge=0, le=255)
    periodic_burst_seconds: float = Field(gt=0, le=3600)
    minimum_burst_interval_seconds: float = Field(gt=0, le=3600)
    burst_frame_count: int = Field(ge=1, le=5)
    burst_frame_interval_seconds: float = Field(ge=0, le=10)
    jpeg_quality: int = Field(ge=20, le=100)
    min_brightness: float = Field(ge=0, le=254)
    max_brightness: float = Field(ge=1, le=255)
    min_sharpness: float = Field(ge=0, le=100_000)

    @model_validator(mode="after")
    def validate_brightness_range(self) -> Self:
        if self.min_brightness >= self.max_brightness:
            raise ValueError("Brightness minimum must be below maximum.")
        return self


class ConfigurationVersionResponse(ApiSchema):
    scope_key: str
    revision: int = Field(ge=0)
    settings: dict[str, object]
    updated_at: AwareDatetime | None = None


class DeviceConfigurationResponse(ApiSchema):
    device_id: UUID
    deployment_profile: Literal["AI_EDGE", "STB_GATEWAY"]
    camera_enabled: bool
    revision: int = Field(ge=0)
    settings: dict[str, object]
    applied_revision: int = Field(ge=0)
    apply_status: Literal["not_configured", "pending", "applied", "error"]
    error_code: str | None = None
    updated_at: AwareDatetime | None = None


class DeviceConfigurationStatusRequest(ApiSchema):
    revision: int = Field(ge=0)
    status: Literal["applied", "error"]
    error_code: str | None = Field(default=None, pattern=r"^[a-z0-9_]{1,64}$")

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.status == "applied" and self.error_code is not None:
            raise ValueError("Applied configuration cannot include an error code.")
        if self.status == "error" and self.error_code is None:
            raise ValueError("Error status must include a safe error code.")
        return self


class CentralRuntimeConfigurationResponse(ApiSchema):
    revision: int = Field(ge=0)
    settings: dict[str, object]
