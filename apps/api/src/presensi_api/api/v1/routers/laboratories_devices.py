from typing import Annotated

from fastapi import APIRouter, Query, status

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES
from presensi_api.api.v1.routers._placeholder import feature_not_implemented
from presensi_api.api.v1.schemas.common import PageResponse
from presensi_api.api.v1.schemas.laboratories import (
    DeviceCreateRequest,
    DeviceResponse,
    LaboratoryCreateRequest,
    LaboratoryResponse,
)

router = APIRouter(tags=["laboratories", "devices"])


@router.get(
    "/laboratories",
    response_model=PageResponse[LaboratoryResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List laboratories",
    description="Contract placeholder; currently returns 501.",
)
def list_laboratories(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[LaboratoryResponse]:
    feature_not_implemented("laboratories")


@router.post(
    "/laboratories",
    response_model=LaboratoryResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Create a laboratory",
    description="Contract placeholder; currently returns 501.",
)
def create_laboratory(request: LaboratoryCreateRequest) -> LaboratoryResponse:
    feature_not_implemented("laboratories")


@router.get(
    "/devices",
    response_model=PageResponse[DeviceResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List devices",
    description="Contract placeholder; currently returns 501.",
)
def list_devices(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[DeviceResponse]:
    feature_not_implemented("devices")


@router.post(
    "/devices",
    response_model=DeviceResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Register a device",
    description="Contract placeholder; currently returns 501.",
)
def create_device(request: DeviceCreateRequest) -> DeviceResponse:
    feature_not_implemented("devices")
