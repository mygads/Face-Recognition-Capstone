from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import String, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import AuthenticatedUser, Permission
from presensi_api.api.v1.schemas.common import PageResponse, Pagination
from presensi_api.api.v1.schemas.laboratories import (
    DeviceCreateRequest,
    DeviceHeartbeatRequest,
    DeviceHeartbeatResponse,
    DeviceLatencySummary,
    DeviceResponse,
    DeviceUpdateRequest,
    LaboratoryCreateRequest,
    LaboratoryResponse,
    LaboratoryUpdateRequest,
)
from presensi_api.db.models import AuditLog, Device, Laboratory
from presensi_api.db.session import get_db_session
from presensi_api.device_health import device_health_status, heartbeat_timeout_seconds

router = APIRouter(tags=["laboratories", "devices"])
DbSession = Annotated[Session, Depends(get_db_session)]


def _timestamp(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _laboratory_response(laboratory: Laboratory) -> LaboratoryResponse:
    return LaboratoryResponse(
        id=laboratory.id,
        code=laboratory.code,
        name=laboratory.name,
        location=laboratory.location,
        is_active=laboratory.is_active,
        created_at=_timestamp(laboratory.created_at),
        updated_at=_timestamp(laboratory.updated_at),
    )


def _device_response(
    device: Device, laboratory: Laboratory, *, now: datetime | None = None
) -> DeviceResponse:
    return DeviceResponse(
        device_id=device.id,
        laboratory_id=laboratory.id,
        laboratory_code=laboratory.code,
        laboratory_name=laboratory.name,
        name=device.name,
        device_type=cast(Literal["edge_pc", "camera_gateway"], device.device_type),
        deployment_profile=cast(
            Literal["AI_EDGE", "STB_GATEWAY"], device.deployment_profile
        ),
        app_version=device.app_version,
        model_version=device.model_version,
        camera_status=cast(
            Literal["unknown", "online", "offline", "error"], device.camera_status
        ),
        latency_summary=(
            DeviceLatencySummary.model_validate(device.latency_summary)
            if device.latency_summary is not None
            else None
        ),
        health_status=cast(
            Literal["online", "offline", "warning"],
            device_health_status(device, now=now),
        ),
        heartbeat_timeout_seconds=heartbeat_timeout_seconds(),
        is_active=device.is_active,
        last_seen_at=(
            _timestamp(device.last_seen_at) if device.last_seen_at is not None else None
        ),
        created_at=_timestamp(device.created_at),
    )


def _not_found(resource: str) -> ApiProblem:
    return ApiProblem(404, "not_found", f"{resource} was not found.")


def _commit(session: Session, code: str, message: str) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiProblem(409, code, message) from exc


@router.get(
    "/laboratories",
    response_model=PageResponse[LaboratoryResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List laboratories",
    dependencies=[Depends(require_permissions(Permission.LABORATORY_READ))],
)
def list_laboratories(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(max_length=200)] = None,
    is_active: bool | None = None,
) -> PageResponse[LaboratoryResponse]:
    query = select(Laboratory)
    count_query = select(func.count()).select_from(Laboratory)
    filters = []
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        filters.append(
            or_(Laboratory.code.ilike(pattern), Laboratory.name.ilike(pattern))
        )
    if is_active is not None:
        filters.append(Laboratory.is_active.is_(is_active))
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)
    total = session.scalar(count_query) or 0
    laboratories = session.scalars(
        query.order_by(Laboratory.code, Laboratory.id).limit(limit).offset(offset)
    ).all()
    return PageResponse(
        items=[_laboratory_response(row) for row in laboratories],
        pagination=Pagination(total=total, limit=limit, offset=offset),
    )


@router.post(
    "/laboratories",
    response_model=LaboratoryResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Create a laboratory",
    dependencies=[Depends(require_permissions(Permission.MANAGE_MASTER_DATA))],
)
def create_laboratory(
    request: LaboratoryCreateRequest, session: DbSession
) -> LaboratoryResponse:
    laboratory = Laboratory(**request.model_dump())
    session.add(laboratory)
    _commit(session, "duplicate_laboratory_code", "Kode laboratorium sudah digunakan.")
    session.refresh(laboratory)
    return _laboratory_response(laboratory)


@router.get(
    "/laboratories/{laboratory_id}",
    response_model=LaboratoryResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Get laboratory details",
    dependencies=[Depends(require_permissions(Permission.LABORATORY_READ))],
)
def get_laboratory(laboratory_id: UUID, session: DbSession) -> LaboratoryResponse:
    laboratory = session.get(Laboratory, laboratory_id)
    if laboratory is None:
        raise _not_found("Laboratory")
    return _laboratory_response(laboratory)


@router.patch(
    "/laboratories/{laboratory_id}",
    response_model=LaboratoryResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Update or deactivate a laboratory",
    dependencies=[Depends(require_permissions(Permission.MANAGE_MASTER_DATA))],
)
def update_laboratory(
    laboratory_id: UUID, request: LaboratoryUpdateRequest, session: DbSession
) -> LaboratoryResponse:
    laboratory = session.get(Laboratory, laboratory_id)
    if laboratory is None:
        raise _not_found("Laboratory")
    for key, value in request.model_dump(exclude_unset=True).items():
        setattr(laboratory, key, value)
    _commit(session, "duplicate_laboratory_code", "Kode laboratorium sudah digunakan.")
    session.refresh(laboratory)
    return _laboratory_response(laboratory)


@router.get(
    "/devices",
    response_model=PageResponse[DeviceResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List devices",
    dependencies=[Depends(require_permissions(Permission.DEVICE_OPERATE))],
)
def list_devices(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(max_length=200)] = None,
    laboratory_id: UUID | None = None,
    health_status: Literal["online", "offline", "warning"] | None = None,
) -> PageResponse[DeviceResponse]:
    query = select(Device, Laboratory).join(
        Laboratory, Device.laboratory_id == Laboratory.id
    )
    count_query = (
        select(func.count())
        .select_from(Device)
        .join(Laboratory, Device.laboratory_id == Laboratory.id)
    )
    filters = []
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=heartbeat_timeout_seconds())
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        filters.append(
            or_(
                Device.name.ilike(pattern),
                Device.id.cast(String).ilike(pattern),
                Laboratory.code.ilike(pattern),
                Laboratory.name.ilike(pattern),
            )
        )
    if laboratory_id is not None:
        filters.append(Device.laboratory_id == laboratory_id)
    if health_status == "online":
        filters.extend(
            [
                Device.is_active.is_(True),
                Device.last_seen_at >= cutoff,
                Device.camera_status == "online",
            ]
        )
    elif health_status == "warning":
        filters.extend(
            [
                Device.is_active.is_(True),
                Device.last_seen_at >= cutoff,
                Device.camera_status != "online",
            ]
        )
    elif health_status == "offline":
        filters.append(
            or_(
                Device.is_active.is_(False),
                Device.last_seen_at.is_(None),
                Device.last_seen_at < cutoff,
            )
        )
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)
    total = session.scalar(count_query) or 0
    rows = session.execute(
        query.order_by(Laboratory.code, Device.name, Device.id)
        .limit(limit)
        .offset(offset)
    ).all()
    devices = [
        _device_response(device, laboratory, now=now) for device, laboratory in rows
    ]
    return PageResponse(
        items=devices,
        pagination=Pagination(total=total, limit=limit, offset=offset),
    )


@router.post(
    "/devices",
    response_model=DeviceResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Register a device",
)
def create_device(
    request: DeviceCreateRequest,
    session: DbSession,
    principal: Annotated[
        AuthenticatedUser, Depends(require_permissions(Permission.MANAGE_MASTER_DATA))
    ],
) -> DeviceResponse:
    laboratory = session.get(Laboratory, request.laboratory_id)
    if laboratory is None:
        raise _not_found("Laboratory")
    if not laboratory.is_active:
        raise ApiProblem(409, "laboratory_inactive", "Laboratorium sedang nonaktif.")
    device = Device(**request.model_dump())
    session.add(device)
    session.flush()
    session.add(
        AuditLog(
            actor_user_id=principal.id,
            action="device.laboratory_assigned",
            entity_type="device",
            entity_id=device.id,
            before_state=None,
            after_state={"laboratory_id": str(device.laboratory_id)},
        )
    )
    _commit(session, "duplicate_device", "Perangkat tidak dapat didaftarkan.")
    session.refresh(device)
    return _device_response(device, laboratory)


@router.patch(
    "/devices/{device_id}",
    response_model=DeviceResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Update device registry or laboratory assignment",
)
def update_device(
    device_id: UUID,
    request: DeviceUpdateRequest,
    session: DbSession,
    principal: Annotated[
        AuthenticatedUser, Depends(require_permissions(Permission.MANAGE_MASTER_DATA))
    ],
) -> DeviceResponse:
    device = session.get(Device, device_id)
    if device is None:
        raise _not_found("Device")
    values = request.model_dump(exclude_unset=True)
    new_laboratory = session.get(
        Laboratory,
        values["laboratory_id"] if "laboratory_id" in values else device.laboratory_id,
    )
    if new_laboratory is None:
        raise _not_found("Laboratory")
    if "laboratory_id" in values and not new_laboratory.is_active:
        raise ApiProblem(409, "laboratory_inactive", "Laboratorium sedang nonaktif.")
    new_profile = values.get("deployment_profile", device.deployment_profile)
    expected_profile = "AI_EDGE" if device.device_type == "edge_pc" else "STB_GATEWAY"
    if new_profile != expected_profile:
        raise ApiProblem(
            422,
            "deployment_profile_mismatch",
            "Profil deployment harus sesuai dengan tipe perangkat.",
        )
    previous_laboratory_id = device.laboratory_id
    for key, value in values.items():
        setattr(device, key, value)
    if device.laboratory_id != previous_laboratory_id:
        session.add(
            AuditLog(
                actor_user_id=principal.id,
                action="device.laboratory_assigned",
                entity_type="device",
                entity_id=device.id,
                before_state={"laboratory_id": str(previous_laboratory_id)},
                after_state={"laboratory_id": str(device.laboratory_id)},
            )
        )
    _commit(session, "device_update_conflict", "Perangkat tidak dapat diperbarui.")
    session.refresh(device)
    return _device_response(device, new_laboratory)


@router.post(
    "/devices/{device_id}/heartbeat",
    response_model=DeviceHeartbeatResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Record a device heartbeat",
    dependencies=[Depends(require_permissions(Permission.DEVICE_OPERATE))],
)
def device_heartbeat(
    device_id: UUID,
    session: DbSession,
    request: DeviceHeartbeatRequest | None = None,
) -> DeviceHeartbeatResponse:
    device = session.get(Device, device_id)
    if device is None:
        raise _not_found("Device")
    if not device.is_active:
        raise ApiProblem(409, "device_inactive", "Perangkat sedang nonaktif.")
    if (
        request is not None
        and request.deployment_profile is not None
        and request.deployment_profile != device.deployment_profile
    ):
        raise ApiProblem(
            409,
            "deployment_profile_mismatch",
            "Profil heartbeat tidak sesuai dengan registry perangkat.",
        )
    now = datetime.now(UTC)
    device.last_seen_at = now
    if request is not None:
        for key in ("app_version", "model_version", "camera_status"):
            value = getattr(request, key)
            if value is not None:
                setattr(device, key, value)
        if request.latency_summary is not None:
            device.latency_summary = request.latency_summary.model_dump(
                exclude_unset=True
            )
    session.commit()
    return DeviceHeartbeatResponse(device_id=device.id, last_seen_at=now)
