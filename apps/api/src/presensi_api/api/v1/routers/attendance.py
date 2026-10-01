from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import AuthenticatedUser, Permission
from presensi_api.api.v1.routers._placeholder import feature_not_implemented
from presensi_api.api.v1.schemas.attendance import (
    AttendanceCorrectionRequest,
    AttendanceCorrectionResponse,
    AttendanceRecordResponse,
    RecognitionEventDecisionResponse,
    RecognitionEventRequest,
)
from presensi_api.api.v1.schemas.common import PageResponse
from presensi_api.attendance_decision import decide_recognition_event
from presensi_api.db.session import get_db_session

router = APIRouter(prefix="/attendance", tags=["attendance"])
DbSession = Annotated[Session, Depends(get_db_session)]
AttendanceOperator = Annotated[
    AuthenticatedUser, Depends(require_permissions(Permission.SESSION_OPERATE))
]


@router.post(
    "/recognition-events",
    response_model=RecognitionEventDecisionResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Record an AI recognition event and decide attendance",
    description=(
        "Stores the recognition event for audit. Creates a final attendance record "
        "only when device, session, roster, liveness, and duplicate rules pass."
    ),
)
def ingest_recognition_event(
    request: RecognitionEventRequest,
    principal: AttendanceOperator,
    session: DbSession,
) -> RecognitionEventDecisionResponse:
    return decide_recognition_event(session, request, principal)


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
