"""merge device camera metrics with current schema history

Revision ID: d18ca0b7e456
Revises: 2b8f61e4c0a7, a7d4e9c20b61
Create Date: 2026-10-03
"""

from __future__ import annotations

from typing import Sequence, Union

revision: str = "d18ca0b7e456"
down_revision: Union[str, Sequence[str], None] = (
    "2b8f61e4c0a7",
    "a7d4e9c20b61",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
