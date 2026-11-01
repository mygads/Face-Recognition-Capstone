"""device edge queue backlog visibility

Revision ID: a1b2c3d4e5f6
Revises: f4e5d6c7b8a9
Create Date: 2026-11-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f4e5d6c7b8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("pending_events", sa.Integer(), nullable=True),
    )
    op.add_column(
        "devices",
        sa.Column("dead_letter_events", sa.Integer(), nullable=True),
    )
    op.add_column(
        "devices",
        sa.Column("queue_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("devices", "queue_updated_at")
    op.drop_column("devices", "dead_letter_events")
    op.drop_column("devices", "pending_events")
