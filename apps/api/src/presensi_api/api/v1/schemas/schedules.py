from datetime import date, time
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

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

    @field_validator("start_time", "end_time")
    @classmethod
    def require_local_wall_clock_time(cls, value: time) -> time:
        if value.tzinfo is not None:
            raise ValueError(
                "Schedule times must be local wall-clock times without an offset."
            )
        return value


class ScheduleUpdateRequest(ApiSchema):
    class_id: UUID | None = None
    laboratory_id: UUID | None = None
    teacher_user_id: UUID | None = None
    subject: str | None = Field(default=None, min_length=1, max_length=120)
    weekday: int | None = Field(default=None, ge=0, le=6)
    start_time: time | None = None
    end_time: time | None = None
    timezone_name: str | None = Field(default=None, min_length=1, max_length=64)
    effective_from: date | None = None
    effective_through: date | None = None
    is_active: bool | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def require_local_wall_clock_time(cls, value: time | None) -> time | None:
        if value is not None and value.tzinfo is not None:
            raise ValueError(
                "Schedule times must be local wall-clock times without an offset."
            )
        return value

    @model_validator(mode="after")
    def validate_patch(self) -> "ScheduleUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        nullable_fields = {"effective_through"}
        if any(
            getattr(self, field) is None and field not in nullable_fields
            for field in self.model_fields_set
        ):
            raise ValueError("Patch fields cannot be null.")
        return self


class ScheduleTeacherResponse(ApiSchema):
    id: UUID
    full_name: str


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
    class_name: str
    laboratory_name: str
    teacher_name: str
    created_at: AwareDatetime
    updated_at: AwareDatetime
