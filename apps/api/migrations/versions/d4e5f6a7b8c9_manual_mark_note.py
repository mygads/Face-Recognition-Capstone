"""store teacher manual-mark note on the attendance record

Revision ID: d4e5f6a7b8c9
Revises: b3c4d5e6f7a8
Create Date: 2026-11-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Manual marks accept a teacher note ("sakit - surat di TU"), but it was
    # only kept inside audit-log JSON and never shown again. A nullable
    # column keeps the write path unchanged for recognition-sourced rows.
    op.add_column(
        "attendance_records",
        sa.Column("note", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("attendance_records", "note")
