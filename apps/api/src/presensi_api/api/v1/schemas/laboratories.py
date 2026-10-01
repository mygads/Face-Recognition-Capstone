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


class DeviceResponse(ApiSchema):
    id: UUID
    laboratory_id: UUID
    name: str
    device_type: Literal["edge_pc", "camera_gateway"]
    is_active: bool
    last_seen_at: AwareDatetime | None
    created_at: AwareDatetime
