"""dashboard summary composite index for session status counts

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-11-02
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Session dashboard polls `WHERE session_id GROUP BY status` every ~2s per
    # connected teacher; the composite index serves filter + grouping from one
    # pass instead of scanning the session's rows.
    op.create_index(
        "ix_attendance_records_session_status",
        "attendance_records",
        ["session_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_attendance_records_session_status", "attendance_records")
