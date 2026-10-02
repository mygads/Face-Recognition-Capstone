from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field, field_validator

from presensi_api.api.v1.schemas.common import ApiSchema


class TokenResponse(ApiSchema):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int = Field(gt=0)
    password_change_required: bool = False


class CurrentUserResponse(ApiSchema):
    id: UUID
    email: str
    full_name: str
    roles: list[str]
    must_change_password: bool


class PasswordChangeRequest(ApiSchema):
    model_config = ConfigDict(str_strip_whitespace=False)

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)

    @field_validator("current_password", "new_password")
    @classmethod
    def reject_whitespace_only(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password cannot contain only whitespace.")
        return value


class PasswordChangeResponse(ApiSchema):
    password_changed: bool
    sign_in_again: bool


class AccountResponse(ApiSchema):
    id: UUID
    email: str
    full_name: str
    is_active: bool
    created_at: AwareDatetime
