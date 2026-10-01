from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from presensi_api.api.v1.schemas.common import ApiSchema


class StudentCreateRequest(ApiSchema):
    student_number: str = Field(min_length=1, max_length=32)
    full_name: str = Field(min_length=1, max_length=200)

    @field_validator("student_number", mode="before")
    @classmethod
    def canonical_student_number(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class StudentUpdateRequest(ApiSchema):
    student_number: str | None = Field(default=None, min_length=1, max_length=32)
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None

    @field_validator("student_number", mode="before")
    @classmethod
    def canonical_student_number(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Patch fields cannot be null.")
        return self


class StudentResponse(ApiSchema):
    id: UUID
    student_number: str
    full_name: str
    is_active: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime


class StudentClassResponse(ApiSchema):
    id: UUID
    code: str
    name: str
    academic_year: str


class StudentDetailResponse(StudentResponse):
    classes: list[StudentClassResponse]


class StudentImportRowResponse(ApiSchema):
    row_number: int = Field(ge=2)
    student_number: str
    full_name: str
    class_code: str
    valid: bool
    errors: list[str]


class StudentImportPreviewResponse(ApiSchema):
    total_rows: int = Field(ge=0)
    valid_rows: int = Field(ge=0)
    invalid_rows: int = Field(ge=0)
    can_commit: bool
    rows: list[StudentImportRowResponse]


class StudentImportCommitResponse(ApiSchema):
    imported_count: int = Field(ge=0)
    class_memberships_created: int = Field(ge=0)


class ClassStudentResponse(ApiSchema):
    id: UUID
    student_number: str
    full_name: str
    is_active: bool


class ClassStudentCreateRequest(ApiSchema):
    student_id: UUID


class ClassCreateRequest(ApiSchema):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    grade: int = Field(ge=1, le=12)
    academic_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    homeroom_teacher_id: UUID | None = None


class ClassUpdateRequest(ApiSchema):
    code: str | None = Field(default=None, min_length=1, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    grade: int | None = Field(default=None, ge=1, le=12)
    academic_year: str | None = Field(default=None, pattern=r"^\d{4}-\d{4}$")
    homeroom_teacher_id: UUID | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        if any(
            getattr(self, field) is None and field != "homeroom_teacher_id"
            for field in self.model_fields_set
        ):
            raise ValueError("Patch fields cannot be null.")
        return self


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


class ClassDetailResponse(ClassResponse):
    students: list[ClassStudentResponse]
