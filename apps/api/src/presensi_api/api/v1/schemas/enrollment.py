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
    model_name: str
    model_version: str
    quality_metadata: dict[str, str | int | float | bool | None]
    created_at: AwareDatetime
    revoked_at: AwareDatetime | None
