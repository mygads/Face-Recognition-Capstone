"""add managed, versioned runtime configuration

Revision ID: e49c72ab31d0
Revises: 7a8f31d4c2b9
Create Date: 2026-10-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e49c72ab31d0"
down_revision: Union[str, None] = "7a8f31d4c2b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column(
            "config_applied_revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "devices",
        sa.Column(
            "config_apply_status",
            sa.String(length=16),
            nullable=False,
            server_default="not_configured",
        ),
    )
    op.add_column("devices", sa.Column("config_error_code", sa.String(length=64)))
    op.add_column("devices", sa.Column("config_applied_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_devices_config_apply_status",
        "devices",
        "config_apply_status IN ('not_configured', 'pending', 'applied', 'error')",
    )
    op.create_check_constraint(
        "ck_devices_config_revision_nonnegative",
        "devices",
        "config_applied_revision >= 0",
    )

    op.create_table(
        "runtime_configuration_versions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("scope_key", sa.String(length=160), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "settings",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_runtime_configuration_versions_revision_positive",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_configuration_versions"),
        sa.UniqueConstraint(
            "scope_key", "revision", name="uq_runtime_config_scope_revision"
        ),
    )


def downgrade() -> None:
    op.drop_table("runtime_configuration_versions")
    op.drop_constraint(
        "ck_devices_config_revision_nonnegative", "devices", type_="check"
    )
    op.drop_constraint("ck_devices_config_apply_status", "devices", type_="check")
    op.drop_column("devices", "config_applied_at")
    op.drop_column("devices", "config_error_code")
    op.drop_column("devices", "config_apply_status")
    op.drop_column("devices", "config_applied_revision")
