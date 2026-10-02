"""merge runtime configuration and bootstrap password change revisions

Revision ID: b2c4d6e8f013
Revises: 8d3a1f6c2b90, e49c72ab31d0
Create Date: 2026-10-02
"""

from __future__ import annotations

from typing import Sequence, Union

revision: str = "b2c4d6e8f013"
down_revision: Union[str, Sequence[str], None] = (
    "8d3a1f6c2b90",
    "e49c72ab31d0",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
