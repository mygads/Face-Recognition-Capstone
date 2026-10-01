from uuid import UUID

from pydantic import AwareDatetime, Field

from presensi_api.api.v1.schemas.common import ApiSchema


class StudentCreateRequest(ApiSchema):
    student_number: str = Field(min_length=1, max_length=32)
    full_name: str = Field(min_length=1, max_length=200)


class StudentResponse(ApiSchema):
    id: UUID
    student_number: str
    full_name: str
    is_active: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ClassCreateRequest(ApiSchema):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    grade: int = Field(ge=1, le=12)
    academic_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    homeroom_teacher_id: UUID | None = None


class ClassResponse(ApiSchema):
    id: UUID
    code: str
    name: str
    grade: int
    academic_year: str
    homeroom_teacher_id: UUID | None
    is_active: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime
