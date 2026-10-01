from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import Permission
from presensi_api.api.v1.routers._placeholder import feature_not_implemented
from presensi_api.api.v1.schemas.common import PageResponse
from presensi_api.api.v1.schemas.students import (
    ClassCreateRequest,
    ClassResponse,
    StudentCreateRequest,
    StudentResponse,
)

router = APIRouter(tags=["students", "classes"])


@router.get(
    "/students",
    response_model=PageResponse[StudentResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List students",
    description="Contract placeholder; currently returns 501.",
    dependencies=[Depends(require_permissions(Permission.ROSTER_READ))],
)
def list_students(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[StudentResponse]:
    feature_not_implemented("students")


@router.post(
    "/students",
    response_model=StudentResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Create a student",
    description="Contract placeholder; currently returns 501.",
    dependencies=[Depends(require_permissions(Permission.MANAGE_MASTER_DATA))],
)
def create_student(request: StudentCreateRequest) -> StudentResponse:
    feature_not_implemented("students")


@router.get(
    "/classes",
    response_model=PageResponse[ClassResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List classes",
    description="Contract placeholder; currently returns 501.",
    dependencies=[Depends(require_permissions(Permission.ROSTER_READ))],
)
def list_classes(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[ClassResponse]:
    feature_not_implemented("classes")


@router.post(
    "/classes",
    response_model=ClassResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Create a class",
    description="Contract placeholder; currently returns 501.",
    dependencies=[Depends(require_permissions(Permission.MANAGE_MASTER_DATA))],
)
def create_class(request: ClassCreateRequest) -> ClassResponse:
    feature_not_implemented("classes")
