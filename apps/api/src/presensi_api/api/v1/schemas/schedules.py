from datetime import date, time
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from presensi_api.api.v1.schemas.common import ApiSchema


class ScheduleCreateRequest(ApiSchema):
    class_id: UUID
    laboratory_id: UUID
    teacher_user_id: UUID
    subject: str = Field(min_length=1, max_length=120)
    weekday: int = Field(ge=0, le=6, description="Monday=0 through Sunday=6.")
    start_time: time
    end_time: time
    timezone_name: str = Field(min_length=1, max_length=64, examples=["Asia/Jakarta"])
    effective_from: date
    effective_through: date | None = None

    @model_validator(mode="after")
    def validate_schedule_window(self) -> "ScheduleCreateRequest":
        if self.start_time >= self.end_time:
            raise ValueError("end_time must be later than start_time")
        if self.effective_through and self.effective_through < self.effective_from:
            raise ValueError("effective_through must not precede effective_from")
        return self


class ScheduleResponse(ApiSchema):
    id: UUID
    class_id: UUID
    laboratory_id: UUID
    teacher_user_id: UUID
    subject: str
    weekday: int
    start_time: time
    end_time: time
    timezone_name: str
    effective_from: date
    effective_through: date | None
    is_active: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime
