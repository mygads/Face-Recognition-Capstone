from datetime import date
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from presensi_api.api.v1.schemas.common import ApiSchema


class AttendanceReportQuery(ApiSchema):
    starts_on: date
    ends_on: date
    class_id: UUID | None = None
    laboratory_id: UUID | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> "AttendanceReportQuery":
        if self.ends_on < self.starts_on:
            raise ValueError("ends_on must be on or after starts_on")
        return self


class AttendanceReportResponse(ApiSchema):
    starts_on: date
    ends_on: date
    total_students: int = Field(ge=0)
    present_count: int = Field(ge=0)
    late_count: int = Field(ge=0)
    absent_count: int = Field(ge=0)
    excused_count: int = Field(ge=0)
    generated_at: AwareDatetime
