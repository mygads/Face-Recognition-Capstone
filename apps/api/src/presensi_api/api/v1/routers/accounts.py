import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.passwords import hash_password
from presensi_api.api.security.roles import AuthenticatedUser, Permission
from presensi_api.api.v1.schemas.auth import (
    AccountResponse,
    StaffAccountCreatedResponse,
    StaffAccountCreateRequest,
)
from presensi_api.api.v1.schemas.common import PageResponse, Pagination
from presensi_api.db.models import AuditLog, Role, User, UserRole
from presensi_api.db.session import get_db_session
from presensi_api.session_lifecycle import as_utc

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get(
    "",
    response_model=PageResponse[AccountResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List user accounts",
    description="List staff and administrator accounts for account management.",
    dependencies=[Depends(require_permissions(Permission.MANAGE_ACCOUNTS))],
)
def list_accounts(
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[AccountResponse]:
    total = session.scalar(select(func.count()).select_from(User)) or 0
    users = session.scalars(
        select(User)
        .order_by(User.email.asc(), User.id.asc())
        .limit(limit)
        .offset(offset)
    ).all()
    return PageResponse(
        items=[
            AccountResponse(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                is_active=user.is_active,
                created_at=as_utc(user.created_at),
            )
            for user in users
        ],
        pagination=Pagination(total=total, limit=limit, offset=offset),
    )


@router.post(
    "",
    response_model=StaffAccountCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Create a teacher or laborant account",
    description=(
        "Creates a staff account with a one-time temporary password. The user "
        "must set a private password before accessing the application."
    ),
)
def create_staff_account(
    request: StaffAccountCreateRequest,
    session: Annotated[Session, Depends(get_db_session)],
    principal: Annotated[
        AuthenticatedUser, Depends(require_permissions(Permission.MANAGE_ACCOUNTS))
    ],
) -> StaffAccountCreatedResponse:
    existing_user = session.scalar(
        select(User.id).where(func.lower(User.email) == request.email)
    )
    if existing_user is not None:
        raise ApiProblem(409, "duplicate_account_email", "Email sudah digunakan.")

    role = session.scalar(select(Role).where(Role.code == request.role))
    if role is None:
        raise ApiProblem(
            409,
            "role_unavailable",
            "Role belum tersedia. Jalankan seed role terlebih dahulu.",
        )

    temporary_password = secrets.token_urlsafe(18)
    user = User(
        email=request.email,
        full_name=request.full_name,
        password_hash=hash_password(temporary_password),
        must_change_password=True,
    )
    try:
        session.add(user)
        session.flush()
        session.add(
            UserRole(
                user_id=user.id,
                role_id=role.id,
                granted_by_user_id=principal.id,
            )
        )
        session.add(
            AuditLog(
                action="account.created",
                actor_user_id=principal.id,
                entity_type="user",
                entity_id=user.id,
                after_state={
                    "role": request.role,
                    "is_active": True,
                    "must_change_password": True,
                },
            )
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiProblem(
            409, "duplicate_account_email", "Email sudah digunakan."
        ) from exc

    return StaffAccountCreatedResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=request.role,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        temporary_password=temporary_password,
    )
