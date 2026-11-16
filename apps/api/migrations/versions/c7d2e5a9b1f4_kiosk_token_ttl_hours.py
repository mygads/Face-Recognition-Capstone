"""kiosk per-screen display token TTL hours

Revision ID: c7d2e5a9b1f4
Revises: d8e9f0a1b2c3
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

revision: str = "c7d2e5a9b1f4"
down_revision: Union[str, Sequence[str], None] = "d8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from alembic import op

    op.add_column(
        "kiosk_screens",
        sa.Column("token_ttl_hours", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_kiosk_screens_token_ttl_range",
        "kiosk_screens",
        "token_ttl_hours IS NULL OR (token_ttl_hours BETWEEN 1 AND 12)",
    )


def downgrade() -> None:
    from alembic import op

    op.drop_constraint(
        "ck_kiosk_screens_token_ttl_range", "kiosk_screens", type_="check"
    )
    op.drop_column("kiosk_screens", "token_ttl_hours")
