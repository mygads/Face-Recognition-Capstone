from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from presensi_api.api.v1.schemas.common import ApiSchema

AttendanceStatus = Literal["present", "late", "absent", "excused"]


class AttendanceRecordResponse(ApiSchema):
    id: UUID
    session_id: UUID
    student_id: UUID
    status: AttendanceStatus
    source: Literal["face_recognition", "manual", "system"]
    recognition_event_id: UUID | None
    recorded_at: AwareDatetime


class AttendanceCorrectionRequest(ApiSchema):
    attendance_record_id: UUID
    corrected_status: AttendanceStatus
    reason: str = Field(min_length=1, max_length=2000)


class AttendanceCorrectionResponse(ApiSchema):
    id: UUID
    attendance_record_id: UUID
    previous_status: AttendanceStatus
    corrected_status: AttendanceStatus
    decision_status: Literal["pending", "approved", "rejected"]
    reason: str
    created_at: AwareDatetime
    decided_at: AwareDatetime | None
