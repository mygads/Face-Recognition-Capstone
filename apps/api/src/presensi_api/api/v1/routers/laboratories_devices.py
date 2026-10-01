from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import Permission
from presensi_api.api.v1.routers._placeholder import feature_not_implemented
from presensi_api.api.v1.schemas.common import PageResponse, Pagination
from presensi_api.api.v1.schemas.laboratories import (
    DeviceCreateRequest,
    DeviceHeartbeatResponse,
    DeviceResponse,
    LaboratoryCreateRequest,
    LaboratoryResponse,
    LaboratoryUpdateRequest,
)
from presensi_api.db.models import Device, Laboratory
from presensi_api.db.session import get_db_session

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
    description="Device operations are defined separately from master data.",
    dependencies=[Depends(require_permissions(Permission.DEVICE_OPERATE))],
)
def list_devices(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[DeviceResponse]:
    del limit, offset
    feature_not_implemented("devices")


@router.post(
    "/devices",
    response_model=DeviceResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Register a device",
    description="Device operations are defined separately from master data.",
    dependencies=[Depends(require_permissions(Permission.MANAGE_MASTER_DATA))],
)
def create_device(request: DeviceCreateRequest) -> DeviceResponse:
    del request
    feature_not_implemented("devices")


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
) -> DeviceHeartbeatResponse:
    device = session.get(Device, device_id)
    if device is None:
        raise _not_found("Device")
    if not device.is_active:
        raise ApiProblem(409, "device_inactive", "Perangkat sedang nonaktif.")
    now = datetime.now(UTC)
    device.last_seen_at = now
    session.commit()
    return DeviceHeartbeatResponse(device_id=device.id, last_seen_at=now)
