from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import FrozenSet
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from presensi_api.db.models import Role, User, UserRole


class RoleCode(StrEnum):
    ADMIN = "ADMIN"
    TEACHER = "TEACHER"
    LABORANT = "LABORANT"


class Permission(StrEnum):
    MANAGE_MASTER_DATA = "manage_master_data"
    MANAGE_ACCOUNTS = "manage_accounts"
    MANAGE_SETTINGS = "manage_settings"
    ROSTER_READ = "roster_read"
    LABORATORY_READ = "laboratory_read"
    DEVICE_OPERATE = "device_operate"
    SCHEDULE_READ = "schedule_read"
    SCHEDULE_MANAGE = "schedule_manage"
    SESSION_OPERATE = "session_operate"
    ENROLLMENT_MANAGE = "enrollment_manage"
    ATTENDANCE_READ = "attendance_read"
    ATTENDANCE_CORRECT = "attendance_correct"
    REPORTS_READ = "reports_read"


ROLE_PERMISSIONS: dict[RoleCode, FrozenSet[Permission]] = {
    RoleCode.ADMIN: frozenset(Permission),
    RoleCode.TEACHER: frozenset(
        {
            Permission.ROSTER_READ,
            Permission.LABORATORY_READ,
            Permission.SCHEDULE_READ,
            Permission.SCHEDULE_MANAGE,
            Permission.SESSION_OPERATE,
            Permission.ATTENDANCE_READ,
            Permission.ATTENDANCE_CORRECT,
            Permission.REPORTS_READ,
        }
    ),
    RoleCode.LABORANT: frozenset(
        {
            Permission.ROSTER_READ,
            Permission.LABORATORY_READ,
            Permission.DEVICE_OPERATE,
            Permission.ENROLLMENT_MANAGE,
        }
    ),
}


LABORANT_GRANTABLE_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.SCHEDULE_READ,
        Permission.SCHEDULE_MANAGE,
        Permission.SESSION_OPERATE,
        Permission.ATTENDANCE_READ,
        Permission.ATTENDANCE_CORRECT,
        Permission.REPORTS_READ,
    }
)


@dataclass(frozen=True)
class AuthenticatedUser:
    id: UUID
    email: str
    full_name: str
    roles: frozenset[RoleCode]
    must_change_password: bool = False
    extra_permissions: frozenset[Permission] = frozenset()

    @property
    def permissions(self) -> frozenset[Permission]:
        base = set(
            permission for role in self.roles for permission in ROLE_PERMISSIONS[role]
        )
        base.update(self.extra_permissions)
        return frozenset(base)


def get_user_roles(session: Session, user_id: UUID) -> frozenset[RoleCode]:
    codes = session.scalars(
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    roles: set[RoleCode] = set()
    for code in codes:
        try:
            roles.add(RoleCode(code))
        except ValueError:
            # Legacy or future roles receive no implicit permission.
            continue
    return frozenset(roles)


def get_user_extra_permissions(
    session: Session, user_id: UUID
) -> frozenset[Permission]:
    try:
        from presensi_api.db.models import UserPermissionGrant
    except Exception:
        return frozenset()
    try:
        rows = session.scalars(
            select(UserPermissionGrant.permission).where(
                UserPermissionGrant.user_id == user_id
            )
        ).all()
    except Exception:
        return frozenset()
    out: set[Permission] = set()
    for raw in rows:
        try:
            out.add(Permission(raw))
        except ValueError:
            continue
    return frozenset(out)


def principal_for_user(session: Session, user: User) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        roles=get_user_roles(session, user.id),
        must_change_password=user.must_change_password,
        extra_permissions=get_user_extra_permissions(session, user.id),
    )
