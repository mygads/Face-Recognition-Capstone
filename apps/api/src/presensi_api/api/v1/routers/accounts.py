import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.passwords import hash_password
from presensi_api.api.security.roles import (
    LABORANT_GRANTABLE_PERMISSIONS,
    AuthenticatedUser,
    Permission,
    RoleCode,
    get_user_extra_permissions,
    get_user_roles,
)
from presensi_api.api.v1.schemas.auth import (
    AccountDetailResponse,
    AccountResponse,
    LaborantAssignmentRequest,
    PermissionGrantRequest,
    StaffAccountCreatedResponse,
    StaffAccountCreateRequest,
    StaffAccountUpdateRequest,
    StaffPasswordResetResponse,
)
from presensi_api.api.v1.schemas.common import PageResponse, Pagination
from presensi_api.db.models import (
    AuditLog,
    LaborantLabAssignment,
    Laboratory,
    Role,
    User,
    UserPermissionGrant,
    UserRole,
)
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


def _detail_for(session: Session, user: User) -> AccountDetailResponse:
    roles = sorted(r.value for r in get_user_roles(session, user.id))
    extras = sorted(p.value for p in get_user_extra_permissions(session, user.id))
    return AccountDetailResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        roles=roles,
        opening_mode=user.opening_mode,
        extra_permissions=extras,
        created_at=as_utc(user.created_at),
    )


@router.get(
    "/{account_id}",
    response_model=AccountDetailResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Get staff account detail",
)
def get_staff_account(
    account_id: str,
    session: Session = Depends(get_db_session),
    principal: AuthenticatedUser = Depends(
        require_permissions(Permission.MANAGE_ACCOUNTS)
    ),
) -> AccountDetailResponse:
    from uuid import UUID as _UUID

    try:
        uid = _UUID(str(account_id))
    except ValueError:
        raise ApiProblem(404, "account_not_found", "Akun tidak ditemukan.")
    user = session.get(User, uid)
    if user is None:
        raise ApiProblem(404, "account_not_found", "Akun tidak ditemukan.")
    return _detail_for(session, user)


@router.patch(
    "/{account_id}",
    response_model=AccountDetailResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Update staff account (active flag, name, opening mode)",
)
def update_staff_account(
    account_id: str,
    request: StaffAccountUpdateRequest,
    session: Session = Depends(get_db_session),
    principal: AuthenticatedUser = Depends(
        require_permissions(Permission.MANAGE_ACCOUNTS)
    ),
) -> AccountDetailResponse:
    from uuid import UUID as _UUID

    try:
        uid = _UUID(str(account_id))
    except ValueError:
        raise ApiProblem(404, "account_not_found", "Akun tidak ditemukan.")
    user = session.get(User, uid)
    if user is None:
        raise ApiProblem(404, "account_not_found", "Akun tidak ditemukan.")
    before = {
        "is_active": user.is_active,
        "full_name": user.full_name,
        "opening_mode": user.opening_mode,
    }
    if request.full_name is not None:
        user.full_name = request.full_name.strip()
    if request.is_active is not None:
        if user.id == principal.id and request.is_active is False:
            raise ApiProblem(
                422, "cannot_deactivate_self", "Akun sendiri tidak bisa dinonaktifkan."
            )
        user.is_active = request.is_active
    if request.opening_mode is not None:
        user.opening_mode = request.opening_mode
    session.add(
        AuditLog(
            action="account.updated",
            actor_user_id=principal.id,
            entity_type="user",
            entity_id=user.id,
            before_state=before,
            after_state={
                "is_active": user.is_active,
                "full_name": user.full_name,
                "opening_mode": user.opening_mode,
            },
        )
    )
    session.commit()
    session.refresh(user)
    return _detail_for(session, user)


@router.post(
    "/{account_id}/reset-password",
    response_model=StaffPasswordResetResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Reset staff password (ADMIN only)",
)
def reset_staff_password(
    account_id: str,
    session: Session = Depends(get_db_session),
    principal: AuthenticatedUser = Depends(
        require_permissions(Permission.MANAGE_ACCOUNTS)
    ),
) -> StaffPasswordResetResponse:
    from uuid import UUID as _UUID

    try:
        uid = _UUID(str(account_id))
    except ValueError:
        raise ApiProblem(404, "account_not_found", "Akun tidak ditemukan.")
    user = session.get(User, uid)
    if user is None:
        raise ApiProblem(404, "account_not_found", "Akun tidak ditemukan.")
    temporary_password = secrets.token_urlsafe(18)
    user.password_hash = hash_password(temporary_password)
    user.must_change_password = True
    user.auth_token_version += 1
    session.add(
        AuditLog(
            action="account.password_reset",
            actor_user_id=principal.id,
            entity_type="user",
            entity_id=user.id,
            after_state={"must_change_password": True},
        )
    )
    session.commit()
    return StaffPasswordResetResponse(
        id=user.id,
        email=user.email,
        must_change_password=True,
        temporary_password=temporary_password,
    )


@router.get(
    "/{account_id}/laborant-assignments",
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List laborant lab assignments",
)
def list_laborant_assignments(
    account_id: str,
    session: Session = Depends(get_db_session),
    principal: AuthenticatedUser = Depends(
        require_permissions(Permission.MANAGE_ACCOUNTS)
    ),
) -> dict[str, object]:
    from uuid import UUID as _UUID

    try:
        uid = _UUID(str(account_id))
    except ValueError:
        raise ApiProblem(404, "account_not_found", "Akun tidak ditemukan.")
    rows = session.scalars(
        select(LaborantLabAssignment).where(LaborantLabAssignment.user_id == uid)
    ).all()
    labs = []
    for row in rows:
        lab = session.get(Laboratory, row.laboratory_id)
        labs.append(
            {
                "laboratory_id": str(row.laboratory_id),
                "code": lab.code if lab else None,
                "name": lab.name if lab else None,
            }
        )
    return {"items": labs}


@router.post(
    "/{account_id}/laborant-assignments",
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Assign laborant to a laboratory",
    status_code=status.HTTP_201_CREATED,
)
def add_laborant_assignment(
    account_id: str,
    request: LaborantAssignmentRequest,
    session: Session = Depends(get_db_session),
    principal: AuthenticatedUser = Depends(
        require_permissions(Permission.MANAGE_ACCOUNTS)
    ),
) -> dict[str, object]:
    from uuid import UUID as _UUID

    try:
        uid = _UUID(str(account_id))
    except ValueError:
        raise ApiProblem(404, "account_not_found", "Akun tidak ditemukan.")
    user = session.get(User, uid)
    lab = session.get(Laboratory, request.laboratory_id)
    if user is None or lab is None:
        raise ApiProblem(
            404, "assignment_target_not_found", "Akun atau lab tidak ditemukan."
        )
    existing = session.get(LaborantLabAssignment, (uid, lab.id))
    if existing is None:
        session.add(
            LaborantLabAssignment(
                user_id=uid, laboratory_id=lab.id, assigned_by_user_id=principal.id
            )
        )
        session.add(
            AuditLog(
                action="laborant.assigned",
                actor_user_id=principal.id,
                entity_type="laborant_lab_assignment",
                entity_id=uid,
                after_state={"laboratory_id": str(lab.id)},
            )
        )
        session.commit()
    return {"user_id": str(uid), "laboratory_id": str(lab.id)}


@router.delete(
    "/{account_id}/laborant-assignments/{laboratory_id}",
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Remove laborant lab assignment",
)
def remove_laborant_assignment(
    account_id: str,
    laboratory_id: str,
    session: Session = Depends(get_db_session),
    principal: AuthenticatedUser = Depends(
        require_permissions(Permission.MANAGE_ACCOUNTS)
    ),
) -> dict[str, object]:
    from uuid import UUID as _UUID

    try:
        uid = _UUID(str(account_id))
        lid = _UUID(str(laboratory_id))
    except ValueError:
        raise ApiProblem(404, "assignment_not_found", "Penugasan tidak ditemukan.")
    row = session.get(LaborantLabAssignment, (uid, lid))
    if row is None:
        raise ApiProblem(404, "assignment_not_found", "Penugasan tidak ditemukan.")
    session.delete(row)
    session.add(
        AuditLog(
            action="laborant.unassigned",
            actor_user_id=principal.id,
            entity_type="laborant_lab_assignment",
            entity_id=uid,
            before_state={"laboratory_id": str(lid)},
            after_state={},
        )
    )
    session.commit()
    return {"removed": True}


@router.get(
    "/{account_id}/permission-grants",
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List optional permission grants for a laborant",
)
def list_permission_grants(
    account_id: str,
    session: Session = Depends(get_db_session),
    principal: AuthenticatedUser = Depends(
        require_permissions(Permission.MANAGE_ACCOUNTS)
    ),
) -> dict[str, object]:
    from uuid import UUID as _UUID

    try:
        uid = _UUID(str(account_id))
    except ValueError:
        raise ApiProblem(404, "account_not_found", "Akun tidak ditemukan.")
    extras = sorted(p.value for p in get_user_extra_permissions(session, uid))
    grantable = sorted(p.value for p in LABORANT_GRANTABLE_PERMISSIONS)
    return {"extra_permissions": extras, "grantable": grantable}


@router.post(
    "/{account_id}/permission-grants",
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Grant an optional permission to a laborant",
    status_code=status.HTTP_201_CREATED,
)
def grant_optional_permission(
    account_id: str,
    request: PermissionGrantRequest,
    session: Session = Depends(get_db_session),
    principal: AuthenticatedUser = Depends(
        require_permissions(Permission.MANAGE_ACCOUNTS)
    ),
) -> dict[str, object]:
    from uuid import UUID as _UUID

    try:
        permission = Permission(str(request.permission).strip())
    except ValueError:
        raise ApiProblem(422, "invalid_permission", "Permission tidak dikenal.")
    if (
        permission not in LABORANT_GRANTABLE_PERMISSIONS
        and RoleCode.ADMIN not in principal.roles
    ):
        raise ApiProblem(
            403, "grant_forbidden", "Permission tidak bisa diberikan ke laboran."
        )
    try:
        uid = _UUID(str(account_id))
    except ValueError:
        raise ApiProblem(404, "account_not_found", "Akun tidak ditemukan.")
    user = session.get(User, uid)
    if user is None:
        raise ApiProblem(404, "account_not_found", "Akun tidak ditemukan.")
    existing = session.get(UserPermissionGrant, (uid, permission.value))
    if existing is None:
        session.add(
            UserPermissionGrant(
                user_id=uid,
                permission=permission.value,
                granted_by_user_id=principal.id,
            )
        )
        session.add(
            AuditLog(
                action="permission.granted",
                actor_user_id=principal.id,
                entity_type="user_permission_grant",
                entity_id=uid,
                after_state={"permission": permission.value},
            )
        )
        session.commit()
    return {"user_id": str(uid), "permission": permission.value}


@router.delete(
    "/{account_id}/permission-grants/{permission}",
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Revoke an optional permission",
)
def revoke_optional_permission(
    account_id: str,
    permission: str,
    session: Session = Depends(get_db_session),
    principal: AuthenticatedUser = Depends(
        require_permissions(Permission.MANAGE_ACCOUNTS)
    ),
) -> dict[str, object]:
    from uuid import UUID as _UUID

    try:
        uid = _UUID(str(account_id))
    except ValueError:
        raise ApiProblem(404, "account_not_found", "Akun tidak ditemukan.")
    row = session.get(UserPermissionGrant, (uid, str(permission)))
    if row is None:
        raise ApiProblem(404, "grant_not_found", "Hak akses tambahan tidak ditemukan.")
    session.delete(row)
    session.add(
        AuditLog(
            action="permission.revoked",
            actor_user_id=principal.id,
            entity_type="user_permission_grant",
            entity_id=uid,
            before_state={"permission": str(permission)},
            after_state={},
        )
    )
    session.commit()
    return {"removed": True}
