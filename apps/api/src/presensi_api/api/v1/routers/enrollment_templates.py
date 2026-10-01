from typing import Annotated

from fastapi import APIRouter, Query, status

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES
from presensi_api.api.v1.routers._placeholder import feature_not_implemented
from presensi_api.api.v1.schemas.common import PageResponse
from presensi_api.api.v1.schemas.enrollment import (
    FaceTemplateResponse,
    TemplateEnrollmentRequest,
)

router = APIRouter(tags=["enrollment", "templates"])


@router.post(
    "/enrollments",
    response_model=FaceTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Enroll a face template",
    description=(
        "Contract placeholder; currently returns 501. The request intentionally "
        "contains no image, blob, or embedding payload."
    ),
)
def create_enrollment(
    request: TemplateEnrollmentRequest,
) -> FaceTemplateResponse:
    feature_not_implemented("template enrollment")


@router.get(
    "/face-templates",
    response_model=PageResponse[FaceTemplateResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List face template metadata",
    description=(
        "Contract placeholder; currently returns 501 and exposes metadata only."
    ),
)
def list_face_templates(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[FaceTemplateResponse]:
    feature_not_implemented("face template metadata")
