"""display PIN lockout counters (lab + kiosk)

Revision ID: c7d8e9f0a1b2
Revises: e6f7a8b9c0d1
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "e6f7a8b9c0d1"


def upgrade() -> None:
    with op.batch_alter_table("laboratories") as batch:
        batch.add_column(
            sa.Column(
                "display_pin_fail_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column("display_pin_locked_until", sa.DateTime(timezone=True))
        )
    with op.batch_alter_table("kiosk_screens") as batch:
        batch.add_column(
            sa.Column(
                "pin_fail_count", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch.add_column(sa.Column("pin_locked_until", sa.DateTime(timezone=True)))


def downgrade() -> None:
    with op.batch_alter_table("kiosk_screens") as batch:
        batch.drop_column("pin_locked_until")
        batch.drop_column("pin_fail_count")
    with op.batch_alter_table("laboratories") as batch:
        batch.drop_column("display_pin_locked_until")
        batch.drop_column("display_pin_fail_count")
