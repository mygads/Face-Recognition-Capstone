from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import Permission
from presensi_api.api.v1.routers._placeholder import feature_not_implemented
from presensi_api.api.v1.schemas.common import PageResponse
from presensi_api.api.v1.schemas.sessions import (
    AttendanceSessionCreateRequest,
    AttendanceSessionResponse,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get(
    "",
    response_model=PageResponse[AttendanceSessionResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List attendance sessions",
    description="Contract placeholder; currently returns 501.",
    dependencies=[Depends(require_permissions(Permission.SESSION_OPERATE))],
)
def list_sessions(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[AttendanceSessionResponse]:
    feature_not_implemented("attendance sessions")


@router.post(
    "",
    response_model=AttendanceSessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Open an attendance session",
    description="Contract placeholder; currently returns 501.",
    dependencies=[Depends(require_permissions(Permission.SESSION_OPERATE))],
)
def open_session(
    request: AttendanceSessionCreateRequest,
) -> AttendanceSessionResponse:
    feature_not_implemented("attendance sessions")


@router.post(
    "/{session_id}/close",
    response_model=AttendanceSessionResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Close an attendance session",
    description="Contract placeholder; currently returns 501.",
    dependencies=[Depends(require_permissions(Permission.SESSION_OPERATE))],
)
def close_session(session_id: UUID) -> AttendanceSessionResponse:
    feature_not_implemented("attendance sessions")
