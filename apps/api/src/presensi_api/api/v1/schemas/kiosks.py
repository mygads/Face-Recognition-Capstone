from uuid import UUID

from pydantic import AwareDatetime, Field

from presensi_api.api.v1.schemas.common import ApiSchema


class KioskCreateRequest(ApiSchema):
    device_id: UUID
    laboratory_id: UUID
    display_name: str = Field(min_length=2, max_length=120)
    camera_label: str | None = Field(default=None, max_length=120)


class KioskUpdateRequest(ApiSchema):
    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    camera_label: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None


class KioskResponse(ApiSchema):
    id: UUID
    device_id: UUID
    laboratory_id: UUID
    display_name: str
    camera_label: str | None = None
    has_pin: bool
    is_active: bool
    last_seen_at: AwareDatetime | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class KioskPinResponse(ApiSchema):
    id: UUID
    temporary_pin: str
