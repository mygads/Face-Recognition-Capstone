from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ApiSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        from_attributes=False,
        str_strip_whitespace=True,
    )


class Pagination(ApiSchema):
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class PageResponse(ApiSchema, Generic[T]):
    items: list[T]
    pagination: Pagination


class ErrorDetail(ApiSchema):
    field: str
    message: str
    code: str


class ApiError(ApiSchema):
    code: str
    message: str
    details: list[ErrorDetail] | None = None


class ErrorEnvelope(ApiSchema):
    error: ApiError
