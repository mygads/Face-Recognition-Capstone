from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from fastapi import APIRouter, Depends

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import Permission
from presensi_api.api.v1.schemas.system_status import AiReadinessResponse

router = APIRouter(prefix="/admin/system", tags=["system-status"])


@router.get(
    "/ai-readiness",
    response_model=AiReadinessResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Check AI model and inference readiness",
    dependencies=[Depends(require_permissions(Permission.MANAGE_SETTINGS))],
)
def get_ai_readiness() -> AiReadinessResponse:
    raw_profile = os.getenv("PRESENSI_LOCAL_AI_PROFILE", "edge").strip().lower()
    profile = "AI_CENTRAL" if raw_profile == "central" else "AI_EDGE"

    yunet_path = os.getenv("PRESENSI_ENROLLMENT_YUNET_MODEL_PATH", "").strip()
    sface_path = os.getenv("PRESENSI_ENROLLMENT_SFACE_MODEL_PATH", "").strip()
    enrollment_ready = bool(
        yunet_path
        and sface_path
        and Path(yunet_path).is_file()
        and Path(sface_path).is_file()
    )

    if profile != "AI_CENTRAL":
        return AiReadinessResponse(
            deployment_profile="AI_EDGE",
            enrollment_models_ready=enrollment_ready,
            central_ai_status="disabled",
            central_ai_models_ready=None,
            central_ai_model_version=None,
            central_ai_thresholds_configured=None,
            central_ai_recognition_ready=None,
        )

    base_url = (
        os.getenv("PRESENSI_AI_SERVICE_BASE_URL", "http://ai-service:8001")
        .strip()
        .rstrip("/")
    )
    try:
        with urlopen(f"{base_url}/health", timeout=1.5) as response:
            payload = json.loads(response.read(16_384))
        if not isinstance(payload, dict):
            raise ValueError("AI health payload must be an object.")
        model_ready = payload.get("models_ready") is True
        raw_model_version = payload.get("model_version")
        model_version = (
            raw_model_version
            if isinstance(raw_model_version, str) and raw_model_version.strip()
            else None
        )
        thresholds_ready = payload.get("thresholds_configured") is True
        recognition_ready = payload.get("recognition_ready") is True
        return AiReadinessResponse(
            deployment_profile="AI_CENTRAL",
            enrollment_models_ready=enrollment_ready,
            central_ai_status="ready" if recognition_ready else "degraded",
            central_ai_models_ready=model_ready,
            central_ai_model_version=model_version,
            central_ai_thresholds_configured=thresholds_ready,
            central_ai_recognition_ready=recognition_ready,
        )
    except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return AiReadinessResponse(
            deployment_profile="AI_CENTRAL",
            enrollment_models_ready=enrollment_ready,
            central_ai_status="unreachable",
            central_ai_models_ready=None,
            central_ai_model_version=None,
            central_ai_thresholds_configured=None,
            central_ai_recognition_ready=None,
        )
