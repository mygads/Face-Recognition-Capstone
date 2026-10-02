"""require password change for local bootstrap users

Revision ID: 8d3a1f6c2b90
    Revises: 91a4e8b6c2f0
Create Date: 2026-10-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "8d3a1f6c2b90"
down_revision: Union[str, None] = "91a4e8b6c2f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "auth_token_version",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "auth_token_version_nonnegative",
        "users",
        "auth_token_version >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("auth_token_version_nonnegative", "users", type_="check")
    op.drop_column("users", "auth_token_version")
    op.drop_column("users", "must_change_password")
