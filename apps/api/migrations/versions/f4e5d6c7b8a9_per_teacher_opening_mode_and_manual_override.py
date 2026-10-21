"""per-teacher opening mode and manual override session status

Revision ID: f4e5d6c7b8a9
Revises: d18ca0b7e456
Create Date: 2026-10-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4e5d6c7b8a9"
down_revision: Union[str, None] = "d18ca0b7e456"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Batch mode: SQLite cannot ADD/DROP CHECK constraints via plain ALTER
    # TABLE, so the constraint changes below must recreate the table there.
    # The partial unique index is handled outside batch (CREATE/DROP INDEX
    # works natively on both backends) with both postgresql_where and
    # sqlite_where so no backend silently allows double-running sessions.
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "opening_mode",
                sa.String(16),
                server_default=sa.text("'manual'"),
                nullable=False,
            )
        )
        batch.create_check_constraint(
            "user_opening_mode",
            "opening_mode IN ('manual', 'automatic')",
        )
    op.execute("UPDATE users SET opening_mode = 'manual' WHERE opening_mode IS NULL")
    with op.batch_alter_table("attendance_sessions") as batch:
        batch.drop_constraint("session_status", type_="check")
        batch.create_check_constraint(
            "session_status",
            "status IN ('active', 'manual_override', 'closed', 'cancelled')",
        )
    op.drop_index(
        "uq_attendance_sessions_active_schedule", table_name="attendance_sessions"
    )
    op.create_index(
        "uq_attendance_sessions_active_schedule",
        "attendance_sessions",
        ["practicum_schedule_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('active', 'manual_override')"),
        sqlite_where=sa.text("status IN ('active', 'manual_override')"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    override_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM attendance_sessions WHERE status = 'manual_override'"
        )
    ).scalar_one()
    if override_count:
        raise RuntimeError(
            "Cannot downgrade: attendance sessions with status 'manual_override' "
            "exist. Close or export them before downgrading."
        )
    automatic_count = bind.execute(
        sa.text("SELECT count(*) FROM users WHERE opening_mode = 'automatic'")
    ).scalar_one()
    if automatic_count:
        raise RuntimeError(
            "Cannot downgrade: users with opening_mode 'automatic' exist. "
            "Reset them to 'manual' before downgrading."
        )
    op.drop_index(
        "uq_attendance_sessions_active_schedule", table_name="attendance_sessions"
    )
    op.create_index(
        "uq_attendance_sessions_active_schedule",
        "attendance_sessions",
        ["practicum_schedule_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )
    with op.batch_alter_table("attendance_sessions") as batch:
        batch.drop_constraint("session_status", type_="check")
        batch.create_check_constraint(
            "session_status",
            "status IN ('active', 'closed', 'cancelled')",
        )
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("user_opening_mode", type_="check")
        batch.drop_column("opening_mode")
