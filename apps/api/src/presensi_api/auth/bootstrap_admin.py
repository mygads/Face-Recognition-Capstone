from __future__ import annotations

import os
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from presensi_api.api.security.passwords import hash_password
from presensi_api.db.models import AuditLog, Role, User, UserRole
from presensi_api.db.session import get_session_factory

BOOTSTRAP_EMAIL = "admin@local.test"
BOOTSTRAP_NAME = "Administrator Lokal"
BOOTSTRAP_PASSWORD_ENV_VAR = "PRESENSI_BOOTSTRAP_PASSWORD"
BOOTSTRAP_DEFAULT_PASSWORD = "1234abcd"


def resolve_bootstrap_password() -> str:
    """Return the development bootstrap password.

    Operators can override the documented default through
    ``PRESENSI_BOOTSTRAP_PASSWORD``; a blank value keeps the default so a
    fresh clone always signs in with the README credential.
    """
    configured = os.getenv(BOOTSTRAP_PASSWORD_ENV_VAR)
    if configured is not None and configured.strip():
        return configured
    return BOOTSTRAP_DEFAULT_PASSWORD


def bootstrap_development_admin(
    session: Session, password: str | None = None
) -> str | None:
    """Create a forced-password-change admin in an empty development database."""
    if os.getenv("APP_ENV", "").casefold() != "development":
        raise RuntimeError(
            "Development admin bootstrap is allowed only in development."
        )
    if session.scalar(select(User.id).limit(1)) is not None:
        return None

    role = session.scalar(select(Role).where(Role.code == "ADMIN"))
    if role is None:
        raise RuntimeError("Roles are not seeded; run the role seed command first.")

    temporary_password = (
        password if password is not None else resolve_bootstrap_password()
    )
    user = User(
        email=BOOTSTRAP_EMAIL,
        full_name=BOOTSTRAP_NAME,
        password_hash=hash_password(temporary_password),
        must_change_password=True,
    )
    session.add(user)
    session.flush()
    session.add(UserRole(user_id=user.id, role_id=role.id))
    session.add(
        AuditLog(
            action="account.development_bootstrap_created",
            entity_type="user",
            entity_id=user.id,
            after_state={"role": "ADMIN", "must_change_password": True},
        )
    )
    return temporary_password


def main() -> int:
    if os.getenv("APP_ENV", "").casefold() != "development":
        print("Refusing to bootstrap an admin outside development.", file=sys.stderr)
        return 2

    try:
        with get_session_factory()() as session, session.begin():
            temporary_password = bootstrap_development_admin(session)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if temporary_password is None:
        print(
            "The development database already contains an account; "
            "no bootstrap account was created and no password was changed or revealed."
        )
        return 0

    print("Created local development administrator.")
    print(f"Email: {BOOTSTRAP_EMAIL}")
    print("The local bootstrap password is documented in the README.")
    print("Change it at first sign-in before using the application.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
