"""store matcher similarity independently from confidence

Revision ID: e208f4a731cd
Revises: d7f0a9416bc3
Create Date: 2026-10-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e208f4a731cd"
down_revision: Union[str, None] = "d7f0a9416bc3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recognition_events",
        sa.Column("similarity", sa.Numeric(precision=8, scale=6), nullable=True),
    )
    op.create_check_constraint(
        "similarity_range",
        "recognition_events",
        "similarity IS NULL OR (similarity >= -1 AND similarity <= 1)",
    )


def downgrade() -> None:
    op.drop_constraint("similarity_range", "recognition_events", type_="check")
    op.drop_column("recognition_events", "similarity")
