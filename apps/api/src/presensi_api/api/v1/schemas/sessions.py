from datetime import time
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from presensi_api.api.v1.schemas.common import ApiSchema


class AttendanceSessionCreateRequest(ApiSchema):
    practicum_schedule_id: UUID
    grace_period_minutes: int = Field(default=15, ge=0, le=1440)


class AttendanceSessionResponse(ApiSchema):
    id: UUID
    practicum_schedule_id: UUID
    status: Literal["active", "closed", "cancelled"]
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
