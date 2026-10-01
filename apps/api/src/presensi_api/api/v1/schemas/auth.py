from pydantic import Field, SecretStr

from presensi_api.api.v1.schemas.common import ApiSchema


class LoginRequest(ApiSchema):
    email: str = Field(
        min_length=3,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        examples=["teacher@example.edu"],
    )
    password: SecretStr = Field(min_length=1, max_length=256)


class RefreshTokenRequest(ApiSchema):
    refresh_token: SecretStr = Field(min_length=1, max_length=4096)


class TokenResponse(ApiSchema):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_seconds: int = Field(gt=0)
