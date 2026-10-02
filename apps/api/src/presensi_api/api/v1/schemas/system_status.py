from typing import Literal

from presensi_api.api.v1.schemas.common import ApiSchema


class AiReadinessResponse(ApiSchema):
    deployment_profile: Literal["AI_EDGE", "AI_CENTRAL"]
    enrollment_models_ready: bool
    central_ai_status: Literal["disabled", "ready", "degraded", "unreachable"]
    central_ai_models_ready: bool | None
    central_ai_model_version: str | None
    central_ai_thresholds_configured: bool | None
    central_ai_recognition_ready: bool | None
