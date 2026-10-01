from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

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
