"""index session time for attendance reporting

Revision ID: f19c8d723a4e
Revises: b4d7f1a83c20
Create Date: 2026-10-01
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "f19c8d723a4e"
down_revision: Union[str, None] = "b4d7f1a83c20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_attendance_sessions_opened_at",
        "attendance_sessions",
        ["opened_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_attendance_sessions_opened_at", table_name="attendance_sessions")
