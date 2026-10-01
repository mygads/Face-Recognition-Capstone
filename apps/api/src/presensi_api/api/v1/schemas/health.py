from typing import Literal

from presensi_api.api.v1.schemas.common import ApiSchema


class HealthResponse(ApiSchema):
    status: Literal["ok"]
