from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from presensi_api.api.v1.schemas.common import ApiSchema

AttendanceStatus = Literal["present", "late", "absent", "excused"]
AttendanceSource = Literal["face_recognition", "manual", "system"]
RecognitionOutcome = Literal["matched", "ambiguous", "no_match", "error", "redacted"]
AttendanceDecisionReason = Literal[
    "device_inactive",
    "device_camera_disabled",
    "device_laboratory_mismatch",
    "session_inactive",
    "student_not_found",
    "student_not_in_session_roster",
    "session_not_accessible",
    "recognition_not_matched",
    "liveness_failed",
    "attendance_already_recorded",
]


class AttendanceRecordResponse(ApiSchema):
    id: UUID
    session_id: UUID
    student_id: UUID
    status: AttendanceStatus
    source: AttendanceSource
    recognition_event_id: UUID | None
    recorded_at: AwareDatetime
    note: str | None = None


class RecognitionEventRequest(ApiSchema):
    event_id: UUID
    device_id: UUID
    session_id: UUID
    student_id: UUID | None
    outcome: RecognitionOutcome
    similarity: Decimal | None = Field(
        default=None, ge=-1, le=1, max_digits=8, decimal_places=6
    )
    confidence: Decimal | None = Field(
        default=None, ge=0, le=1, max_digits=7, decimal_places=6
    )
    margin: Decimal | None = Field(
        default=None, ge=0, le=1, max_digits=7, decimal_places=6
    )
    liveness_passed: bool | None = None
    liveness_score: Decimal | None = Field(
        default=None, ge=0, le=1, max_digits=7, decimal_places=6
    )
    occurred_at: AwareDatetime
    model_name: str = Field(min_length=1, max_length=120)
    model_version: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def matched_event_has_candidate_and_score(self) -> Self:
        if self.outcome == "matched" and self.student_id is None:
            raise ValueError("A matched event requires a candidate student_id.")
        if (
            self.outcome == "matched"
            and self.similarity is None
            and self.confidence is None
        ):
            raise ValueError("A matched event requires similarity or confidence.")
        return self


class RecognitionEventDecisionResponse(ApiSchema):
    event_id: UUID
    recognition_event_id: UUID
    outcome: RecognitionOutcome
    decision: Literal["attendance_recorded", "no_attendance"]
    reason: AttendanceDecisionReason | None
    attendance: AttendanceRecordResponse | None
    replayed: bool


class AttendanceCorrectionRequest(ApiSchema):
    attendance_record_id: UUID | None = None
    session_id: UUID | None = None
    student_id: UUID | None = None
    corrected_status: AttendanceStatus
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def strip_and_validate_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A correction reason is required.")
        return cleaned

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        has_record = self.attendance_record_id is not None
        has_missing = self.session_id is not None and self.student_id is not None
        if not has_record and not has_missing:
            raise ValueError(
                "Isi attendance_record_id atau pasangan session_id + student_id."
            )
        if has_record and has_missing:
            raise ValueError("Pilih satu jenis koreksi saja.")
        return self


class AttendanceCorrectionDecisionRequest(ApiSchema):
    decision: Literal["approved", "rejected"]
    decision_note: str | None = Field(default=None, max_length=2000)

    @field_validator("decision_note")
    @classmethod
    def strip_and_validate_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class AttendanceCorrectionResponse(ApiSchema):
    id: UUID
    attendance_record_id: UUID | None
    session_id: UUID | None = None
    student_id: UUID | None = None
    previous_status: AttendanceStatus
    corrected_status: AttendanceStatus
    decision_status: Literal["pending", "approved", "rejected"]
    reason: str
    created_at: AwareDatetime
    decided_at: AwareDatetime | None
    decided_by_user_id: UUID | None = None
    decision_note: str | None = None


class ManualMarkRequest(ApiSchema):
    student_id: UUID
    status: AttendanceStatus
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def strip_and_validate_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ManualMarkResponse(ApiSchema):
    record: AttendanceRecordResponse
