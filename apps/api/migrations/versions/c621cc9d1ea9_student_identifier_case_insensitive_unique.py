"""enforce case-insensitive student identifiers

Revision ID: c621cc9d1ea9
Revises: 61ac91fc3bc2
Create Date: 2026-10-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c621cc9d1ea9"
down_revision: Union[str, None] = "61ac91fc3bc2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_students_student_number_ci",
        "students",
        [sa.text("lower(student_number)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_students_student_number_ci", table_name="students")
