from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from presensi_api.api.v1.schemas.common import ApiSchema


class LaboratoryCreateRequest(ApiSchema):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    location: str | None = Field(default=None, max_length=200)


class LaboratoryResponse(ApiSchema):
    id: UUID
    code: str
    name: str
    location: str | None
    is_active: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime


class LaboratoryUpdateRequest(ApiSchema):
    code: str | None = Field(default=None, min_length=1, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    location: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        if any(
            getattr(self, field) is None and field != "location"
            for field in self.model_fields_set
        ):
            raise ValueError("Patch fields cannot be null.")
        return self


class DeviceCreateRequest(ApiSchema):
    laboratory_id: UUID
    name: str = Field(min_length=1, max_length=120)
    device_type: Literal["edge_pc", "camera_gateway"]
    deployment_profile: Literal["AI_EDGE", "STB_GATEWAY"]

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        expected = "AI_EDGE" if self.device_type == "edge_pc" else "STB_GATEWAY"
        if self.deployment_profile != expected:
            raise ValueError("Deployment profile must match the device type.")
        return self


class DeviceUpdateRequest(ApiSchema):
    laboratory_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    deployment_profile: Literal["AI_EDGE", "STB_GATEWAY"] | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Patch fields cannot be null.")
        return self


class DeviceLatencySummary(ApiSchema):
    p50_ms: float | None = Field(default=None, ge=0, le=600_000)
    p95_ms: float | None = Field(default=None, ge=0, le=600_000)


class DeviceHeartbeatRequest(ApiSchema):
    deployment_profile: Literal["AI_EDGE", "STB_GATEWAY"] | None = None
    app_version: str | None = Field(default=None, min_length=1, max_length=80)
    model_version: str | None = Field(default=None, min_length=1, max_length=128)
    camera_status: Literal["unknown", "online", "offline", "error"] | None = None
    latency_summary: DeviceLatencySummary | None = None


class DeviceResponse(ApiSchema):
    device_id: UUID
    laboratory_id: UUID
    laboratory_code: str
    laboratory_name: str
    name: str
    device_type: Literal["edge_pc", "camera_gateway"]
    deployment_profile: Literal["AI_EDGE", "STB_GATEWAY"]
    app_version: str | None
    model_version: str | None
    camera_status: Literal["unknown", "online", "offline", "error"]
    latency_summary: DeviceLatencySummary | None
    health_status: Literal["online", "offline", "warning"]
    heartbeat_timeout_seconds: int = Field(ge=5, le=3600)
    is_active: bool
    last_seen_at: AwareDatetime | None
    created_at: AwareDatetime


class DeviceHeartbeatResponse(ApiSchema):
    device_id: UUID
    last_seen_at: AwareDatetime
