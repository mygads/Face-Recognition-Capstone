from typing import Literal
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


class StaffAccountCreateRequest(ApiSchema):
    full_name: str = Field(min_length=2, max_length=200)
    email: str = Field(min_length=6, max_length=320)
    role: Literal["TEACHER", "LABORANT"]

    @field_validator("email")
    @classmethod
    def normalize_and_validate_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        local_part, separator, domain = normalized.partition("@")
        if (
            not separator
            or not local_part
            or not domain
            or any(character.isspace() for character in normalized)
            or "." not in domain
            or domain.startswith(".")
            or domain.endswith(".")
        ):
            raise ValueError("Masukkan alamat email yang valid.")
        return normalized


class StaffAccountCreatedResponse(ApiSchema):
    id: UUID
    email: str
    full_name: str
    role: Literal["TEACHER", "LABORANT"]
    is_active: bool
    must_change_password: bool
    temporary_password: str
