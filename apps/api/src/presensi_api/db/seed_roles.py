from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from presensi_api.db.models import Role
from presensi_api.db.session import get_engine

ROLE_SEEDS: tuple[tuple[str, str, str], ...] = (
    ("admin", "Administrator", "Manages system configuration and users."),
    ("teacher", "Teacher", "Manages practicum sessions and attendance."),
    ("lab_assistant", "Lab assistant", "Supports laboratory operations."),
    ("student", "Student", "Views personal attendance information."),
)


def role_id_for_code(code: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://presensi.local/roles/{code}")


def seed_roles(session: Session) -> int:
    """Insert missing baseline roles and return the number added."""
    existing = set(session.scalars(select(Role.code)))
    missing = [role for role in ROLE_SEEDS if role[0] not in existing]
    session.add_all(
        [
            Role(
                id=role_id_for_code(code), code=code, name=name, description=description
            )
            for code, name, description in missing
        ]
    )
    return len(missing)


def main() -> None:
    with get_engine().begin() as connection:
        with Session(bind=connection) as session, session.begin():
            added = seed_roles(session)
    print(f"Role seed complete; {added} role(s) added.")


if __name__ == "__main__":
    main()
