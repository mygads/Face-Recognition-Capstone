from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import func, select

from presensi_api.api.security.passwords import hash_password
from presensi_api.api.security.roles import RoleCode
from presensi_api.db.models import AuditLog, Role, User, UserRole
from presensi_api.db.session import get_session_factory


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create an internal user account without exposing its password "
            "in shell history."
        )
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", required=True)
    parser.add_argument(
        "--role", required=True, choices=[role.value for role in RoleCode]
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    email = args.email.strip().casefold()
    if len(email) > 320 or "@" not in email:
        print("A valid email address is required.", file=sys.stderr)
        return 2
    if not args.full_name.strip() or len(args.full_name) > 200:
        print("A full name between 1 and 200 characters is required.", file=sys.stderr)
        return 2

    password = getpass.getpass("Password (minimum 12 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if len(password) < 12:
        print("Password must contain at least 12 characters.", file=sys.stderr)
        return 2
    if password != confirmation:
        print("Passwords do not match.", file=sys.stderr)
        return 2

    with get_session_factory()() as session, session.begin():
        if session.scalar(select(User.id).where(func.lower(User.email) == email)):
            print("An account with that email already exists.", file=sys.stderr)
            return 2
        role = session.scalar(select(Role).where(Role.code == args.role))
        if role is None:
            print(
                "Roles are not seeded. Run the role seed command first.",
                file=sys.stderr,
            )
            return 2
        user = User(
            email=email,
            full_name=args.full_name.strip(),
            password_hash=hash_password(password),
        )
        session.add(user)
        session.flush()
        session.add(UserRole(user_id=user.id, role_id=role.id))
        session.add(
            AuditLog(
                action="account.created",
                entity_type="user",
                entity_id=user.id,
                after_state={"role": args.role, "result": "success"},
            )
        )
    print(f"Created {args.role} account for {email}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
