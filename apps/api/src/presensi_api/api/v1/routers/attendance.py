from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import Permission
from presensi_api.api.v1.routers._placeholder import feature_not_implemented
from presensi_api.api.v1.schemas.attendance import (
    AttendanceCorrectionRequest,
    AttendanceCorrectionResponse,
    AttendanceRecordResponse,
)
from presensi_api.api.v1.schemas.common import PageResponse

router = APIRouter(prefix="/attendance", tags=["attendance"])


@router.get(
    "",
    response_model=PageResponse[AttendanceRecordResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List final attendance records",
    description="Contract placeholder; currently returns 501.",
    dependencies=[Depends(require_permissions(Permission.ATTENDANCE_READ))],
)
def list_attendance(
    session_id: UUID | None = None,
    student_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[AttendanceRecordResponse]:
    feature_not_implemented("attendance records")


@router.post(
    "/corrections",
    response_model=AttendanceCorrectionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Request an attendance correction",
    description="Contract placeholder; currently returns 501.",
    dependencies=[Depends(require_permissions(Permission.ATTENDANCE_CORRECT))],
)
def request_attendance_correction(
    request: AttendanceCorrectionRequest,
) -> AttendanceCorrectionResponse:
    feature_not_implemented("attendance corrections")
