from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from presensi_api.api.v1.schemas.common import ApiSchema


class TemplateEnrollmentRequest(ApiSchema):
    student_id: UUID
    device_id: UUID
    model_name: str = Field(min_length=1, max_length=120)
    model_version: str = Field(min_length=1, max_length=80)


class FaceTemplateResponse(ApiSchema):
    id: UUID
    student_id: UUID
    enrollment_batch_id: UUID
    model_name: str
    model_version: str
    quality_metadata: dict[str, str | int | float | bool | None]
    created_at: AwareDatetime
    revoked_at: AwareDatetime | None


class EnrollmentStudentStatusResponse(ApiSchema):
    id: UUID
    student_number: str
    full_name: str
    template_status: Literal["not_enrolled", "enrolled", "needs_reenrollment"]


class EnrollmentDuplicateWarning(ApiSchema):
    student_id: UUID
    student_number: str
    full_name: str
    similarity: float = Field(ge=-1, le=1)


class EnrollmentCaptureResultResponse(ApiSchema):
    student_id: UUID
    enrollment_batch_id: UUID
    template_status: Literal["enrolled", "needs_reenrollment"]
    accepted_frames: int = Field(ge=0)
    rejected_frames: int = Field(ge=0)
    template_count: int = Field(ge=0, le=5)
    duplicate_warnings: list[EnrollmentDuplicateWarning] = Field(default_factory=list)
    confirmation_required: bool = True


class TemplateRevocationResponse(ApiSchema):
    student_id: UUID
    enrollment_batch_id: UUID
    revoked_templates: int = Field(ge=1)
    revoked_at: AwareDatetime
