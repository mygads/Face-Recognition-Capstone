from typing import Literal

from presensi_api.api.v1.schemas.common import ApiSchema


class AiReadinessResponse(ApiSchema):
    deployment_profile: Literal["AI_EDGE", "AI_CENTRAL"]
    enrollment_models_ready: bool
    enrollment_model_version: str | None
    enrollment_quality_revision: int
    central_ai_status: Literal["disabled", "ready", "degraded", "unreachable"]
    central_ai_models_ready: bool | None
    central_ai_model_version: str | None
    central_ai_thresholds_configured: bool | None
    central_ai_recognition_ready: bool | None
    central_ai_config_desired_revision: int | None
    central_ai_config_applied_revision: int | None
    central_ai_config_sync_status: (
        Literal["disabled", "pending", "applied", "error", "unavailable"] | None
    )
