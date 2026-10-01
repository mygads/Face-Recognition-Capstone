from typing import Annotated

from fastapi import APIRouter, Query, status

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES
from presensi_api.api.v1.routers._placeholder import feature_not_implemented
from presensi_api.api.v1.schemas.common import PageResponse
from presensi_api.api.v1.schemas.schedules import (
    ScheduleCreateRequest,
    ScheduleResponse,
)

router = APIRouter(prefix="/schedules", tags=["schedules"])


@router.get(
    "",
    response_model=PageResponse[ScheduleResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List practicum schedules",
    description="Contract placeholder; currently returns 501.",
)
def list_schedules(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[ScheduleResponse]:
    feature_not_implemented("practicum schedules")


@router.post(
    "",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Create a practicum schedule",
    description="Contract placeholder; currently returns 501.",
)
def create_schedule(request: ScheduleCreateRequest) -> ScheduleResponse:
    feature_not_implemented("practicum schedules")
