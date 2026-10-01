from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from presensi_api.api.v1.schemas.common import ApiSchema


class ActiveDeviceSessionResponse(ApiSchema):
    session_id: UUID
    session_status: Literal["active"]
    session_starts_at: AwareDatetime
    session_ends_at: AwareDatetime
    generated_at: AwareDatetime
    expires_at: AwareDatetime


class SessionTemplateResponse(ApiSchema):
    model_name: str
    model_version: str
    values: list[float] = Field(min_length=1, repr=False)
    normalized: Literal[True] = True


class SessionRosterStudentResponse(ApiSchema):
    student_id: UUID
    student_number: str
    full_name: str
    templates: list[SessionTemplateResponse]


class ActiveSessionCacheResponse(ActiveDeviceSessionResponse):
    device_id: UUID
    model_name: str
    model_version: str
    roster: list[SessionRosterStudentResponse]


class DeviceCredentialResponse(ApiSchema):
    device_id: UUID
    token: str = Field(repr=False)
    expires_at: AwareDatetime
    previous_token_valid_until: AwareDatetime | None = None


class DeviceRuntimeStatusResponse(ApiSchema):
    device_id: UUID
    active: Literal[True]
    deployment_profile: Literal["AI_EDGE", "STB_GATEWAY"]


class DeviceCredentialRotationRequest(ApiSchema):
    reason: str = Field(min_length=1, max_length=200)


class DeviceHeartbeatDeviceResponse(ApiSchema):
    device_id: UUID
    last_seen_at: AwareDatetime
    credential_expires_at: AwareDatetime
