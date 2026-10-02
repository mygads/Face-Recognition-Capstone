"""add remote camera enable state and system-opened sessions

Revision ID: a7d4e9c20b61
Revises: e49c72ab31d0
Create Date: 2026-10-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7d4e9c20b61"
down_revision: Union[str, None] = "c91e42a7d3f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("devices") as batch:
        batch.add_column(
            sa.Column(
                "camera_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch.drop_constraint(op.f("ck_devices_camera_status"), type_="check")
        batch.create_check_constraint(
            "camera_status",
            "camera_status IN ('unknown', 'online', 'offline', 'error', 'disabled')",
        )
    with op.batch_alter_table("attendance_sessions") as batch:
        batch.alter_column(
            "opened_by_user_id",
            existing_type=sa.Uuid(),
            nullable=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    null_actor_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM attendance_sessions WHERE opened_by_user_id IS NULL"
        )
    ).scalar_one()
    if null_actor_count:
        raise RuntimeError(
            "Cannot downgrade: attendance sessions were opened automatically. "
            "Preserve those rows or export them before downgrading."
        )
    with op.batch_alter_table("attendance_sessions") as batch:
        batch.alter_column(
            "opened_by_user_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )
    with op.batch_alter_table("devices") as batch:
        batch.drop_constraint(op.f("ck_devices_camera_status"), type_="check")
        batch.create_check_constraint(
            "camera_status",
            "camera_status IN ('unknown', 'online', 'offline', 'error')",
        )
        batch.drop_column("camera_enabled")
