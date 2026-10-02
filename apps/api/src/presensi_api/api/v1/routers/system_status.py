from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Literal, cast
from urllib.error import URLError
from urllib.request import urlopen

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import Permission
from presensi_api.api.v1.schemas.system_status import AiReadinessResponse
from presensi_api.db.session import get_db_session
from presensi_api.runtime_configuration import configuration_values

router = APIRouter(prefix="/admin/system", tags=["system-status"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.get(
    "/ai-readiness",
    response_model=AiReadinessResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Check AI model and inference readiness",
    dependencies=[Depends(require_permissions(Permission.MANAGE_SETTINGS))],
)
def get_ai_readiness(session: DbSession) -> AiReadinessResponse:
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
    enrollment_revision, _, _ = configuration_values(session, "enrollment")

    if profile != "AI_CENTRAL":
        return AiReadinessResponse(
            deployment_profile="AI_EDGE",
            enrollment_models_ready=enrollment_ready,
            enrollment_quality_revision=enrollment_revision,
            central_ai_status="disabled",
            central_ai_models_ready=None,
            central_ai_model_version=None,
            central_ai_thresholds_configured=None,
            central_ai_recognition_ready=None,
            central_ai_config_desired_revision=None,
            central_ai_config_applied_revision=None,
            central_ai_config_sync_status=None,
        )

    central_revision, _, _ = configuration_values(session, "AI_CENTRAL")

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
        raw_applied_revision = payload.get("configuration_revision")
        applied_revision = (
            raw_applied_revision
            if type(raw_applied_revision) is int and raw_applied_revision >= 0
            else None
        )
        raw_sync_status = payload.get("configuration_sync_status")
        if not isinstance(raw_sync_status, str) or raw_sync_status not in {
            "disabled",
            "pending",
            "applied",
            "error",
            "unavailable",
        }:
            raw_sync_status = "unavailable"
        if raw_sync_status == "disabled" and central_revision > 0:
            raw_sync_status = "pending"
        return AiReadinessResponse(
            deployment_profile="AI_CENTRAL",
            enrollment_models_ready=enrollment_ready,
            enrollment_quality_revision=enrollment_revision,
            central_ai_status="ready" if recognition_ready else "degraded",
            central_ai_models_ready=model_ready,
            central_ai_model_version=model_version,
            central_ai_thresholds_configured=thresholds_ready,
            central_ai_recognition_ready=recognition_ready,
            central_ai_config_desired_revision=central_revision,
            central_ai_config_applied_revision=applied_revision,
            central_ai_config_sync_status=cast(
                Literal["disabled", "pending", "applied", "error", "unavailable"],
                raw_sync_status,
            ),
        )
    except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return AiReadinessResponse(
            deployment_profile="AI_CENTRAL",
            enrollment_models_ready=enrollment_ready,
            enrollment_quality_revision=enrollment_revision,
            central_ai_status="unreachable",
            central_ai_models_ready=None,
            central_ai_model_version=None,
            central_ai_thresholds_configured=None,
            central_ai_recognition_ready=None,
            central_ai_config_desired_revision=central_revision,
            central_ai_config_applied_revision=None,
            central_ai_config_sync_status="unavailable",
        )
