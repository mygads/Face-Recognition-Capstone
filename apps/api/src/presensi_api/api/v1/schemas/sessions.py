from datetime import time
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from presensi_api.api.v1.schemas.attendance import (
    AttendanceDecisionReason,
    AttendanceStatus,
    RecognitionOutcome,
)
from presensi_api.api.v1.schemas.common import ApiSchema


class AttendanceSessionCreateRequest(ApiSchema):
    practicum_schedule_id: UUID
    grace_period_minutes: int = Field(default=15, ge=0, le=1440)


class AttendanceSessionResponse(ApiSchema):
    id: UUID
    practicum_schedule_id: UUID
    status: Literal["active", "closed", "cancelled"]
    opened_automatically: bool
    opened_at: AwareDatetime
    closed_at: AwareDatetime | None
    grace_period_minutes: int
    student_count: int = Field(ge=0)
    subject: str
    class_name: str
    laboratory_name: str
    teacher_name: str
    weekday: int
    start_time: time
    end_time: time
    timezone_name: str
    scheduled_end_at: AwareDatetime


class OpenableScheduleResponse(ApiSchema):
    id: UUID
    subject: str
    class_name: str
    laboratory_name: str
    teacher_name: str
    weekday: int
    start_time: time
    end_time: time
    timezone_name: str


class SessionOpeningPolicy(ApiSchema):
    mode: Literal["manual", "automatic"] = "manual"
    auto_open_minutes_before: int = Field(default=0, ge=0, le=15)
    auto_open_minutes_after: int = Field(default=15, ge=0, le=15)
    default_grace_period_minutes: int = Field(default=15, ge=0, le=1440)


class SessionOpeningPolicyResponse(SessionOpeningPolicy):
    revision: int = Field(ge=0)
    updated_at: AwareDatetime | None = None


class SessionAttendanceSummary(ApiSchema):
    total_roster: int = Field(ge=0)
    present: int = Field(ge=0)
    late: int = Field(ge=0)
    not_present: int = Field(ge=0)


class SessionDashboardDevice(ApiSchema):
    id: UUID
    name: str
    device_type: Literal["edge_pc", "camera_gateway"]
    is_online: bool
    health_status: Literal["online", "offline", "warning"]
    camera_status: Literal["unknown", "online", "offline", "error", "disabled"]
    last_seen_at: AwareDatetime | None


class SessionRecentActivity(ApiSchema):
    id: UUID
    occurred_at: AwareDatetime
    kind: Literal["recognition", "attendance"]
    student_name: str | None
    recognition_outcome: RecognitionOutcome | None
    attendance_status: AttendanceStatus | None
    decision_reason: AttendanceDecisionReason | None


class SessionDashboardSnapshot(ApiSchema):
    session_id: UUID
    session_status: Literal["active", "closed", "cancelled"]
    generated_at: AwareDatetime
    summary: SessionAttendanceSummary
    devices: list[SessionDashboardDevice]
    recent_activity: list[SessionRecentActivity]
