import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.dependencies import get_current_user, require_permissions
from presensi_api.api.security.passwords import hash_password
from presensi_api.api.security.roles import (
    LABORANT_GRANTABLE_PERMISSIONS,
    AuthenticatedUser,
    Permission,
    RoleCode,
    get_user_extra_permissions,
    get_user_roles,
    missing_prerequisites,
)
from presensi_api.api.v1.schemas.auth import (
    AccountDetailResponse,
    AccountResponse,
    ClassLaboratoryRequest,
    LaborantAssignmentRequest,
    PermissionGrantRequest,
    StaffAccountCreatedResponse,
    StaffAccountCreateRequest,
    StaffAccountUpdateRequest,
    StaffPasswordResetResponse,
    TeacherAssignmentRequest,
)
from presensi_api.api.v1.schemas.common import PageResponse, Pagination
from presensi_api.db.models import (
    AuditLog,
    AuthSession,
    ClassLaboratory,
    LaborantLabAssignment,
    Laboratory,
    Role,
    SchoolClass,
    TeacherClassAssignment,
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
    "/class-laboratories",
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List class-laboratory service mappings",
)
def list_class_laboratories(
    session: Session = Depends(get_db_session),
    principal: AuthenticatedUser = Depends(
        require_permissions(Permission.MANAGE_ACCOUNTS)
    ),
) -> dict[str, object]:
    rows = session.scalars(select(ClassLaboratory)).all()
    return {
        "items": [
            {"class_id": str(r.class_id), "laboratory_id": str(r.laboratory_id)}
            for r in rows
        ]
    }


@router.post(
    "/class-laboratories",
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Map a class to a laboratory",
    status_code=status.HTTP_201_CREATED,
)
def add_class_laboratory(
    request: ClassLaboratoryRequest,
    session: Session = Depends(get_db_session),
    principal: AuthenticatedUser = Depends(
        require_permissions(Permission.MANAGE_ACCOUNTS)
    ),
) -> dict[str, object]:
    klass = session.get(SchoolClass, request.class_id)
    lab = session.get(Laboratory, request.laboratory_id)
    if klass is None:
        raise ApiProblem(404, "class_not_found", "Kelas tidak ditemukan.")
    if lab is None:
        raise ApiProblem(404, "laboratory_not_found", "Laboratorium tidak ditemukan.")
    existing = session.get(ClassLaboratory, (request.class_id, request.laboratory_id))
    if existing is None:
        session.add(
            ClassLaboratory(
                class_id=request.class_id,
                laboratory_id=request.laboratory_id,
                assigned_by_user_id=principal.id,
            )
        )
        session.add(
            AuditLog(
                action="class.laboratory_mapped",
                actor_user_id=principal.id,
                entity_type="class_laboratory",
                entity_id=request.class_id,
                after_state={"laboratory_id": str(request.laboratory_id)},
            )
        )
        session.commit()
    return {
        "class_id": str(request.class_id),
        "laboratory_id": str(request.laboratory_id),
    }


@router.delete(
    "/class-laboratories/{class_id}/{laboratory_id}",
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Remove a class-laboratory mapping",
)
def remove_class_laboratory(
    class_id: str,
    laboratory_id: str,
    session: Session = Depends(get_db_session),
    principal: AuthenticatedUser = Depends(
        require_permissions(Permission.MANAGE_ACCOUNTS)
    ),
) -> dict[str, object]:
    from uuid import UUID as _UUID

    try:
        cid = _UUID(str(class_id))
        lid = _UUID(str(laboratory_id))
    except ValueError:
        raise ApiProblem(404, "mapping_not_found", "Relasi tidak ditemukan.")
    row = session.get(ClassLaboratory, (cid, lid))
    if row is None:
        raise ApiProblem(404, "mapping_not_found", "Relasi tidak ditemukan.")
    session.delete(row)
    session.add(
        AuditLog(
            action="class.laboratory_unmapped",
            actor_user_id=principal.id,
            entity_type="class_laboratory",
            entity_id=cid,
            before_state={"laboratory_id": str(lid)},
            after_state={},
        )
    )
    session.commit()
    return {"removed": True}


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
    summary="Update staff account (active flag, name, opening mode, role)",
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
        if request.is_active is False and user.is_active:
            admin_role = session.scalar(select(Role).where(Role.code == "ADMIN"))
            if admin_role is not None:
                admin_ids = set(
                    session.scalars(
                        select(UserRole.user_id).where(
                            UserRole.role_id == admin_role.id
                        )
                    ).all()
                )
                if user.id in admin_ids:
                    others_active = (
                        session.scalar(
                            select(func.count())
                            .select_from(User)
                            .join(UserRole, UserRole.user_id == User.id)
                            .where(
                                UserRole.role_id == admin_role.id,
                                User.is_active.is_(True),
                                User.id != user.id,
                            )
                        )
                        or 0
                    )
                    if others_active == 0:
                        raise ApiProblem(
                            422,
                            "cannot_deactivate_last_admin",
                            "Admin aktif terakhir tidak bisa dinonaktifkan.",
                        )
            user.is_active = False
            user.auth_token_version += 1
            session.query(AuthSession).filter(
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
            ).update(
                {AuthSession.revoked_at: func.now()},
                synchronize_session=False,
            )
        elif request.is_active is True:
            user.is_active = True
    if request.opening_mode is not None:
        user.opening_mode = request.opening_mode
    role_changed: str | None = None
    released: dict[str, int] = {}
    if request.role is not None:
        current_roles = set(
            session.scalars(
                select(Role.code)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user.id)
            ).all()
        )
        if "ADMIN" in current_roles:
            raise ApiProblem(
                422,
                "role_change_admin_unsupported",
                "Role admin tidak dapat diubah lewat endpoint ini.",
            )
        if user.id == principal.id:
            raise ApiProblem(
                422, "cannot_change_own_role", "Role akun sendiri tidak bisa diubah."
            )
        if request.role not in current_roles:
            target_role = session.scalar(select(Role).where(Role.code == request.role))
            if target_role is None:
                raise ApiProblem(404, "role_unavailable", "Role tujuan belum tersedia.")
            session.query(UserRole).filter(UserRole.user_id == user.id).delete(
                synchronize_session=False
            )
            session.add(UserRole(user_id=user.id, role_id=target_role.id))
            if request.role == "TEACHER":
                lab_rel = (
                    session.query(LaborantLabAssignment)
                    .filter(LaborantLabAssignment.user_id == user.id)
                    .delete(synchronize_session=False)
                )
                grant_rel = (
                    session.query(UserPermissionGrant)
                    .filter(UserPermissionGrant.user_id == user.id)
                    .delete(synchronize_session=False)
                )
                released = {
                    "laborant_lab_assignments": lab_rel,
                    "permission_grants": grant_rel,
                }
            else:
                class_rel = (
                    session.query(TeacherClassAssignment)
                    .filter(TeacherClassAssignment.user_id == user.id)
                    .delete(synchronize_session=False)
                )
                released = {"teacher_class_assignments": class_rel}
                user.opening_mode = "manual"
            role_changed = request.role
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
                "role_changed": role_changed,
                "released_assignments": released,
                "deactivation_reason": (
                    request.deactivation_reason.strip()
                    if request.deactivation_reason
                    else None
                ),
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


def require_manage_accounts_or_self(
    account_id: str,
    principal: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Admin pengelola atau pemilik akun sendiri (untuk scope chip/dashboard)."""
    if Permission.MANAGE_ACCOUNTS in principal.permissions:
        return principal
    if str(principal.id) == str(account_id):
        return principal
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions.",
    )


@router.get(
    "/{account_id}/laborant-assignments",
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List laborant lab assignments",
)
def list_laborant_assignments(
    account_id: str,
    session: Session = Depends(get_db_session),
    principal: AuthenticatedUser = Depends(require_manage_accounts_or_self),
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
    current = {
        Permission(row)
        for row in session.scalars(
            select(UserPermissionGrant.permission).where(
                UserPermissionGrant.user_id == uid
            )
        ).all()
        if row in Permission._value2member_map_
    }
    current.add(permission)
    missing = missing_prerequisites(frozenset(current))
    if missing:
        raise ApiProblem(
            422,
            "grant_missing_prerequisite",
            "Hak akses membutuhkan prasyarat: "
            + "; ".join(f"{k} butuh {', '.join(v)}" for k, v in missing.items()),
        )
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
    remaining = {
        Permission(r)
        for r in session.scalars(
            select(UserPermissionGrant.permission).where(
                UserPermissionGrant.user_id == uid
            )
        ).all()
        if r in Permission._value2member_map_ and r != str(permission)
    }
    missing = missing_prerequisites(frozenset(remaining))
    if missing:
        raise ApiProblem(
            422,
            "grant_revoke_blocked",
            "Pencabutan diblokir karena hak lain membutuhkan: "
            + "; ".join(f"{k} butuh {', '.join(v)}" for k, v in missing.items()),
        )
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


@router.get(
    "/{account_id}/teacher-assignments",
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List teacher class assignments",
)
def list_teacher_assignments(
    account_id: str,
    session: Session = Depends(get_db_session),
    principal: AuthenticatedUser = Depends(require_manage_accounts_or_self),
) -> dict[str, object]:
    from uuid import UUID as _UUID

    try:
        uid = _UUID(str(account_id))
    except ValueError:
        raise ApiProblem(404, "account_not_found", "Akun tidak ditemukan.")
    rows = session.scalars(
        select(TeacherClassAssignment).where(TeacherClassAssignment.user_id == uid)
    ).all()
    items = []
    for row in rows:
        klass = session.get(SchoolClass, row.class_id)
        items.append(
            {
                "class_id": str(row.class_id),
                "code": klass.code if klass else None,
                "name": klass.name if klass else None,
                "starts_on": row.starts_on.isoformat() if row.starts_on else None,
                "ends_on": row.ends_on.isoformat() if row.ends_on else None,
                "is_substitute": row.is_substitute,
            }
        )
    return {"items": items}


@router.get(
    "/classes/{class_id}/teacher-assignments",
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List teachers assigned to a class",
)
def list_class_teachers(
    class_id: str,
    session: Session = Depends(get_db_session),
    principal: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, object]:
    """Guru yang ditugaskan ke kelas beserta masa berlaku (untuk detail kelas)."""
    from uuid import UUID as _UUID

    from presensi_api.api.security.roles import RoleCode
    from presensi_api.api.security.scope import is_admin, teacher_class_ids

    try:
        cid = _UUID(str(class_id))
    except ValueError:
        raise ApiProblem(404, "class_not_found", "Kelas tidak ditemukan.")
    if not is_admin(principal):
        allowed = RoleCode.TEACHER in principal.roles and cid in teacher_class_ids(
            session, principal.id
        )
        if not allowed:
            from fastapi import HTTPException
            from fastapi import status as _status

            raise HTTPException(
                status_code=_status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            )
    rows = session.scalars(
        select(TeacherClassAssignment).where(TeacherClassAssignment.class_id == cid)
    ).all()
    items = []
    for row in rows:
        teacher = session.get(User, row.user_id)
        items.append(
            {
                "user_id": str(row.user_id),
                "full_name": teacher.full_name if teacher else None,
                "starts_on": row.starts_on.isoformat() if row.starts_on else None,
                "ends_on": row.ends_on.isoformat() if row.ends_on else None,
                "is_substitute": row.is_substitute,
            }
        )
    return {"items": items}


@router.post(
    "/{account_id}/teacher-assignments",
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Assign teacher to a class",
    status_code=status.HTTP_201_CREATED,
)
def add_teacher_assignment(
    account_id: str,
    request: TeacherAssignmentRequest,
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
    klass = session.get(SchoolClass, request.class_id)
    if user is None:
        raise ApiProblem(404, "account_not_found", "Akun tidak ditemukan.")
    if klass is None:
        raise ApiProblem(404, "class_not_found", "Kelas tidak ditemukan.")
    existing = session.get(TeacherClassAssignment, (uid, request.class_id))
    if existing is None:
        session.add(
            TeacherClassAssignment(
                user_id=uid,
                class_id=request.class_id,
                assigned_by_user_id=principal.id,
                starts_on=request.starts_on,
                ends_on=request.ends_on,
                is_substitute=request.is_substitute,
            )
        )
        session.add(
            AuditLog(
                action="teacher.assigned",
                actor_user_id=principal.id,
                entity_type="teacher_class_assignment",
                entity_id=uid,
                after_state={
                    "class_id": str(request.class_id),
                    "is_substitute": request.is_substitute,
                },
            )
        )
        session.commit()
    return {"user_id": str(uid), "class_id": str(request.class_id)}


@router.delete(
    "/{account_id}/teacher-assignments/{class_id}",
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Remove a teacher class assignment",
)
def remove_teacher_assignment(
    account_id: str,
    class_id: str,
    session: Session = Depends(get_db_session),
    principal: AuthenticatedUser = Depends(
        require_permissions(Permission.MANAGE_ACCOUNTS)
    ),
) -> dict[str, object]:
    from uuid import UUID as _UUID

    try:
        uid = _UUID(str(account_id))
        cid = _UUID(str(class_id))
    except ValueError:
        raise ApiProblem(404, "assignment_not_found", "Penugasan tidak ditemukan.")
    row = session.get(TeacherClassAssignment, (uid, cid))
    if row is None:
        raise ApiProblem(404, "assignment_not_found", "Penugasan tidak ditemukan.")
    session.delete(row)
    session.add(
        AuditLog(
            action="teacher.unassigned",
            actor_user_id=principal.id,
            entity_type="teacher_class_assignment",
            entity_id=uid,
            before_state={"class_id": str(cid)},
            after_state={},
        )
    )
    session.commit()
    return {"removed": True}
