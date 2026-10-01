"""add device registry metadata and health state

Revision ID: b4d7f1a83c20
Revises: e208f4a731cd
Create Date: 2026-10-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4d7f1a83c20"
down_revision: Union[str, None] = "e208f4a731cd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "devices", sa.Column("deployment_profile", sa.String(length=32), nullable=True)
    )
    op.add_column("devices", sa.Column("app_version", sa.String(length=80)))
    op.add_column("devices", sa.Column("model_version", sa.String(length=128)))
    op.add_column(
        "devices",
        sa.Column(
            "camera_status",
            sa.String(length=16),
            server_default=sa.text("'unknown'"),
            nullable=False,
        ),
    )
    op.add_column(
        "devices",
        sa.Column(
            "latency_summary",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
        ),
    )
    op.execute(
        "UPDATE devices SET deployment_profile = CASE "
        "WHEN device_type = 'camera_gateway' THEN 'STB_GATEWAY' "
        "ELSE 'AI_EDGE' END"
    )
    op.alter_column(
        "devices",
        "deployment_profile",
        nullable=False,
        server_default=sa.text("'AI_EDGE'"),
    )
    op.create_check_constraint(
        "deployment_profile",
        "devices",
        "deployment_profile IN ('AI_EDGE', 'STB_GATEWAY')",
    )
    op.create_check_constraint(
        "deployment_profile_matches_type",
        "devices",
        "(device_type = 'edge_pc' AND deployment_profile = 'AI_EDGE') OR "
        "(device_type = 'camera_gateway' AND deployment_profile = 'STB_GATEWAY')",
    )
    op.create_check_constraint(
        "camera_status",
        "devices",
        "camera_status IN ('unknown', 'online', 'offline', 'error')",
    )
    op.create_index("ix_devices_last_seen_at", "devices", ["last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_devices_last_seen_at", table_name="devices")
    op.drop_constraint("camera_status", "devices", type_="check")
    op.drop_constraint("deployment_profile_matches_type", "devices", type_="check")
    op.drop_constraint("deployment_profile", "devices", type_="check")
    op.drop_column("devices", "latency_summary")
    op.drop_column("devices", "camera_status")
    op.drop_column("devices", "model_version")
    op.drop_column("devices", "app_version")
    op.drop_column("devices", "deployment_profile")
