from datetime import date
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, model_validator

from presensi_api.api.v1.schemas.common import ApiSchema, PageResponse

ReportStatus = Literal["present", "late", "absent", "excused", "not_recorded"]
ExportFormat = Literal["csv", "xlsx"]


class AttendanceReportQuery(ApiSchema):
    starts_on: date
    ends_on: date
    student_id: UUID | None = None
    student_number: str | None = Field(default=None, min_length=1, max_length=32)
    class_id: UUID | None = None
    laboratory_id: UUID | None = None
    session_id: UUID | None = None
    status: ReportStatus | None = None
    timezone_name: str = Field(default="Asia/Jakarta", min_length=1, max_length=64)
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_range_and_timezone(self) -> "AttendanceReportQuery":
        if self.ends_on < self.starts_on:
            raise ValueError("ends_on must be on or after starts_on")
        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                "timezone_name must be a recognized IANA timezone"
            ) from exc
        return self


class AttendanceReportRow(ApiSchema):
    attendance_record_id: UUID | None
    session_id: UUID
    student_id: UUID
    student_number: str
    student_name: str
    class_id: UUID
    class_code: str
    class_name: str
    laboratory_id: UUID
    laboratory_code: str
    laboratory_name: str
    subject: str
    teacher_name: str
    status: ReportStatus
    source: Literal["face_recognition", "manual", "system"] | None
    session_opened_at: AwareDatetime
    recorded_at: AwareDatetime | None


class AttendanceReportPage(PageResponse[AttendanceReportRow]):
    pass


class AttendanceReportResponse(ApiSchema):
    starts_on: date
    ends_on: date
    total_rows: int = Field(ge=0)
    present_count: int = Field(ge=0)
    late_count: int = Field(ge=0)
    absent_count: int = Field(ge=0)
    excused_count: int = Field(ge=0)
    not_recorded_count: int = Field(ge=0)
    generated_at: AwareDatetime


class AttendanceReportExportQuery(AttendanceReportQuery):
    format: ExportFormat
