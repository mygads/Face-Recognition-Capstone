from typing import Annotated

from fastapi import APIRouter, Depends, Query

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import Permission
from presensi_api.api.v1.routers._placeholder import feature_not_implemented
from presensi_api.api.v1.schemas.auth import AccountResponse
from presensi_api.api.v1.schemas.common import PageResponse

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get(
    "",
    response_model=PageResponse[AccountResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List user accounts",
    description="Contract placeholder; currently returns 501.",
    dependencies=[Depends(require_permissions(Permission.MANAGE_ACCOUNTS))],
)
def list_accounts(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[AccountResponse]:
    feature_not_implemented("account management")
