from uuid import UUID

from pydantic import AwareDatetime, Field

from presensi_api.api.v1.schemas.common import ApiSchema


class TokenResponse(ApiSchema):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int = Field(gt=0)


class CurrentUserResponse(ApiSchema):
    id: UUID
    email: str
    full_name: str
    roles: list[str]


class AccountResponse(ApiSchema):
    id: UUID
    email: str
    full_name: str
    is_active: bool
    created_at: AwareDatetime
