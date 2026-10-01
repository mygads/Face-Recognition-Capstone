from typing import Annotated

from fastapi import APIRouter, Depends, Query

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import Permission
from presensi_api.api.v1.routers._placeholder import feature_not_implemented
from presensi_api.api.v1.schemas.reports import (
    AttendanceReportQuery,
    AttendanceReportResponse,
)

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get(
    "/attendance",
    response_model=AttendanceReportResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Get an attendance summary",
    description="Contract placeholder; currently returns 501.",
    dependencies=[Depends(require_permissions(Permission.REPORTS_READ))],
)
def get_attendance_report(
    query: Annotated[AttendanceReportQuery, Query()],
) -> AttendanceReportResponse:
    feature_not_implemented("attendance reports")
