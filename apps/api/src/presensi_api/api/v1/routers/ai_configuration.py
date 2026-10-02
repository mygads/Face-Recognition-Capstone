from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.request_rate_limit import DeviceActor
from presensi_api.api.security.roles import AuthenticatedUser, Permission
from presensi_api.api.v1.schemas.ai_configuration import (
    CentralRuntimeConfigurationResponse,
    ConfigurationVersionResponse,
    DeviceConfigurationResponse,
    DeviceConfigurationStatusRequest,
    EnrollmentQualityConfiguration,
    RecognitionConfiguration,
    StbGatewayConfiguration,
)
from presensi_api.db.models import Device
from presensi_api.db.session import get_db_session
from presensi_api.runtime_configuration import (
    central_configuration_from_environment,
    configuration_values,
    device_scope_key,
    enrollment_quality_from_environment,
    latest_configuration,
    managed_ai_sync_token_matches,
    save_configuration,
)

router = APIRouter(tags=["ai-configuration"])
DbSession = Annotated[Session, Depends(get_db_session)]
ManageSettings = Annotated[
    AuthenticatedUser, Depends(require_permissions(Permission.MANAGE_SETTINGS))
]


def _version_response(session: Session, scope_key: str) -> ConfigurationVersionResponse:
    version = latest_configuration(session, scope_key)
    if version is None:
        values = (
            enrollment_quality_from_environment()
            if scope_key == "enrollment"
            else central_configuration_from_environment()
        )
        return ConfigurationVersionResponse(
            scope_key=scope_key, revision=0, settings=values, updated_at=None
        )
    updated_at = version.created_at
    if updated_at.tzinfo is None or updated_at.utcoffset() is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return ConfigurationVersionResponse(
        scope_key=scope_key,
        revision=version.revision,
        settings=dict(version.settings),
        updated_at=updated_at,
    )


def _device_configuration(
    session: Session, device: Device
) -> DeviceConfigurationResponse:
    revision, settings, updated_at = configuration_values(
        session, device_scope_key(device.id)
    )
    if updated_at is not None and (
        updated_at.tzinfo is None or updated_at.utcoffset() is None
    ):
        updated_at = updated_at.replace(tzinfo=UTC)
    return DeviceConfigurationResponse(
        device_id=device.id,
        deployment_profile=cast(
            Literal["AI_EDGE", "STB_GATEWAY"], device.deployment_profile
        ),
        revision=revision,
        settings=settings,
        applied_revision=device.config_applied_revision,
        apply_status=cast(
            Literal["not_configured", "pending", "applied", "error"],
            device.config_apply_status,
        ),
        error_code=device.config_error_code,
        updated_at=updated_at,
    )


def _device(session: Session, device_id: UUID) -> Device:
    device = session.get(Device, device_id)
    if device is None or not device.is_active:
        raise ApiProblem(404, "not_found", "Perangkat tidak ditemukan atau nonaktif.")
    return device


@router.get(
    "/admin/settings/enrollment-quality",
    response_model=ConfigurationVersionResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    dependencies=[Depends(require_permissions(Permission.MANAGE_SETTINGS))],
    summary="Read enrollment capture quality settings",
)
def get_enrollment_quality(
    session: DbSession,
) -> ConfigurationVersionResponse:
    return _version_response(session, "enrollment")


@router.put(
    "/admin/settings/enrollment-quality",
    response_model=ConfigurationVersionResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Publish enrollment capture quality settings",
)
def put_enrollment_quality(
    request: EnrollmentQualityConfiguration,
    session: DbSession,
    actor: ManageSettings,
) -> ConfigurationVersionResponse:
    version = save_configuration(
        session,
        scope_key="enrollment",
        settings=request.model_dump(mode="json"),
        actor=actor,
    )
    return _version_response(session, version.scope_key)


@router.get(
    "/admin/settings/ai-central",
    response_model=ConfigurationVersionResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    dependencies=[Depends(require_permissions(Permission.MANAGE_SETTINGS))],
    summary="Read AI Central recognition settings",
)
def get_central_settings(session: DbSession) -> ConfigurationVersionResponse:
    return _version_response(session, "AI_CENTRAL")


@router.put(
    "/admin/settings/ai-central",
    response_model=ConfigurationVersionResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Publish AI Central recognition settings",
)
def put_central_settings(
    request: RecognitionConfiguration,
    session: DbSession,
    actor: ManageSettings,
) -> ConfigurationVersionResponse:
    version = save_configuration(
        session,
        scope_key="AI_CENTRAL",
        settings=request.model_dump(mode="json"),
        actor=actor,
    )
    return _version_response(session, version.scope_key)


@router.get(
    "/admin/settings/devices/{device_id}",
    response_model=DeviceConfigurationResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    dependencies=[Depends(require_permissions(Permission.MANAGE_SETTINGS))],
    summary="Read a device's remotely managed runtime settings",
)
def get_managed_device_settings(
    device_id: UUID, session: DbSession
) -> DeviceConfigurationResponse:
    return _device_configuration(session, _device(session, device_id))


@router.put(
    "/admin/settings/devices/{device_id}/ai-edge",
    response_model=DeviceConfigurationResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Publish AI_EDGE runtime settings for a device",
)
def put_edge_settings(
    device_id: UUID,
    request: RecognitionConfiguration,
    session: DbSession,
    actor: ManageSettings,
) -> DeviceConfigurationResponse:
    device = _device(session, device_id)
    if device.deployment_profile != "AI_EDGE":
        raise ApiProblem(
            409, "deployment_profile_mismatch", "Perangkat ini bukan AI_EDGE."
        )
    if (
        request.min_top1_similarity is None
        or request.min_top1_top2_margin is None
        or not (request.calibration_reference or "").strip()
    ):
        raise ApiProblem(
            422,
            "calibration_reference_required",
            "Isi kedua threshold dari laporan kalibrasi sebelum menerapkannya "
            "ke AI_EDGE.",
        )
    device.config_apply_status = "pending"
    device.config_error_code = None
    save_configuration(
        session,
        scope_key=device_scope_key(device.id),
        settings=request.model_dump(mode="json"),
        actor=actor,
    )
    return _device_configuration(session, device)


@router.put(
    "/admin/settings/devices/{device_id}/stb-gateway",
    response_model=DeviceConfigurationResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Publish STB gateway capture settings for a device",
)
def put_gateway_settings(
    device_id: UUID,
    request: StbGatewayConfiguration,
    session: DbSession,
    actor: ManageSettings,
) -> DeviceConfigurationResponse:
    device = _device(session, device_id)
    if device.deployment_profile != "STB_GATEWAY":
        raise ApiProblem(
            409, "deployment_profile_mismatch", "Perangkat ini bukan STB_GATEWAY."
        )
    device.config_apply_status = "pending"
    device.config_error_code = None
    save_configuration(
        session,
        scope_key=device_scope_key(device.id),
        settings=request.model_dump(mode="json"),
        actor=actor,
    )
    return _device_configuration(session, device)


@router.get(
    "/devices/{device_id}/runtime-configuration",
    response_model=DeviceConfigurationResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Fetch the latest device-scoped runtime configuration",
)
def get_device_runtime_configuration(
    device_id: UUID, principal: DeviceActor, session: DbSession
) -> DeviceConfigurationResponse:
    device = _device(session, device_id)
    if principal.device.id != device.id:
        raise ApiProblem(403, "device_id_mismatch", "Credential perangkat tidak cocok.")
    return _device_configuration(session, device)


@router.post(
    "/devices/{device_id}/runtime-configuration/status",
    response_model=DeviceConfigurationResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Report whether a device applied its latest configuration",
)
def report_device_runtime_configuration(
    device_id: UUID,
    request: DeviceConfigurationStatusRequest,
    principal: DeviceActor,
    session: DbSession,
) -> DeviceConfigurationResponse:
    device = _device(session, device_id)
    if principal.device.id != device.id:
        raise ApiProblem(403, "device_id_mismatch", "Credential perangkat tidak cocok.")
    desired_revision, _, _ = configuration_values(session, device_scope_key(device.id))
    if request.revision > desired_revision:
        raise ApiProblem(
            409,
            "configuration_revision_unknown",
            "Versi konfigurasi belum diterbitkan.",
        )
    if request.revision < desired_revision:
        if request.status == "applied":
            device.config_applied_revision = request.revision
        device.config_apply_status = "pending"
        device.config_error_code = None
    elif request.status == "applied":
        device.config_applied_revision = request.revision
        device.config_apply_status = "applied"
        device.config_error_code = None
        device.config_applied_at = datetime.now(UTC)
    else:
        device.config_apply_status = "error"
        device.config_error_code = request.error_code
    session.commit()
    session.refresh(device)
    return _device_configuration(session, device)


@router.get(
    "/internal/ai-central-configuration",
    response_model=CentralRuntimeConfigurationResponse,
    include_in_schema=False,
)
def get_internal_central_ai_configuration(
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> CentralRuntimeConfigurationResponse:
    token = (
        authorization.partition(" ")[2].strip()
        if authorization and authorization.lower().startswith("bearer ")
        else None
    )
    if not managed_ai_sync_token_matches(token):
        raise ApiProblem(
            401, "invalid_service_credentials", "Autentikasi service gagal."
        )
    revision, settings, _ = configuration_values(session, "AI_CENTRAL")
    if revision == 0:
        settings = central_configuration_from_environment()
    return CentralRuntimeConfigurationResponse(revision=revision, settings=settings)
