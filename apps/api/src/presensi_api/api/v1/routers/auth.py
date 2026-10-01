from fastapi import APIRouter

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES
from presensi_api.api.v1.routers._placeholder import feature_not_implemented
from presensi_api.api.v1.schemas.auth import (
    LoginRequest,
    RefreshTokenRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Exchange credentials for tokens",
    description="Contract placeholder; currently returns 501.",
)
def login(request: LoginRequest) -> TokenResponse:
    feature_not_implemented("authentication")


@router.post(
    "/refresh",
    response_model=TokenResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Refresh authentication tokens",
    description="Contract placeholder; currently returns 501.",
)
def refresh_tokens(request: RefreshTokenRequest) -> TokenResponse:
    feature_not_implemented("authentication")
