"""normalize baseline role codes

Revision ID: 61ac91fc3bc2
Revises: c35e8b617a08
Create Date: 2026-10-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "61ac91fc3bc2"
down_revision: Union[str, None] = "c35e8b617a08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Preserve historical student-role assignments without granting them app access.
    for old_code, new_code, new_name in (
        ("admin", "ADMIN", "Administrator"),
        ("teacher", "TEACHER", "Teacher"),
        ("lab_assistant", "LABORANT", "Laborant"),
        ("student", "LEGACY_STUDENT", "Legacy student"),
    ):
        op.execute(
            sa.text(
                "UPDATE roles SET code = :new_code, name = :new_name "
                "WHERE code = :old_code"
            ).bindparams(old_code=old_code, new_code=new_code, new_name=new_name)
        )


def downgrade() -> None:
    for new_code, old_code, old_name in (
        ("ADMIN", "admin", "Administrator"),
        ("TEACHER", "teacher", "Teacher"),
        ("LABORANT", "lab_assistant", "Laboratory assistant"),
        ("LEGACY_STUDENT", "student", "Student"),
    ):
        op.execute(
            sa.text(
                "UPDATE roles SET code = :old_code, name = :old_name "
                "WHERE code = :new_code"
            ).bindparams(new_code=new_code, old_code=old_code, old_name=old_name)
        )
