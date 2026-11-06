"""laborant scope, ews follow-up, display PIN, correction missing-record

Revision ID: f5a6b7c8d9e0
Revises: d4e5f6a7b8c9
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from alembic import op

    # laboratories display PIN
    op.add_column(
        "laboratories", sa.Column("display_pin_hash", sa.String(255), nullable=True)
    )
    op.add_column(
        "laboratories",
        sa.Column("display_pin_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # laborant assignments
    op.create_table(
        "laborant_lab_assignments",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("laboratory_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["laboratory_id"], ["laboratories.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("user_id", "laboratory_id"),
        sa.UniqueConstraint(
            "user_id", "laboratory_id", name="uq_laborant_lab_user_lab"
        ),
    )
    op.create_index(
        "ix_laborant_lab_lab_id", "laborant_lab_assignments", ["laboratory_id"]
    )
    # permission grants
    op.create_table(
        "user_permission_grants",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("permission", sa.String(64), nullable=False),
        sa.Column("granted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("user_id", "permission"),
        sa.UniqueConstraint("user_id", "permission", name="uq_user_permission_grant"),
    )
    op.create_index(
        "ix_user_permission_grant_user", "user_permission_grants", ["user_id"]
    )
    # ews follow ups
    op.create_table(
        "ews_follow_ups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ews_follow_ups_student_id", "ews_follow_ups", ["student_id"])
    op.create_index("ix_ews_follow_ups_created_at", "ews_follow_ups", ["created_at"])
    # corrections missing-record support
    op.add_column(
        "attendance_corrections", sa.Column("session_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "attendance_corrections", sa.Column("student_id", sa.Uuid(), nullable=True)
    )
    try:
        op.alter_column(
            "attendance_corrections",
            "attendance_record_id",
            existing_type=sa.Uuid(),
            nullable=True,
        )
    except Exception:
        pass
    try:
        op.create_foreign_key(
            "fk_corr_session",
            "attendance_corrections",
            "attendance_sessions",
            ["session_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    except Exception:
        pass
    try:
        op.create_foreign_key(
            "fk_corr_student",
            "attendance_corrections",
            "students",
            ["student_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    except Exception:
        pass


def downgrade() -> None:
    from alembic import op

    try:
        op.drop_constraint(
            "fk_corr_student", "attendance_corrections", type_="foreignkey"
        )
    except Exception:
        pass
    try:
        op.drop_constraint(
            "fk_corr_session", "attendance_corrections", type_="foreignkey"
        )
    except Exception:
        pass
    try:
        op.drop_column("attendance_corrections", "student_id")
    except Exception:
        pass
    try:
        op.drop_column("attendance_corrections", "session_id")
    except Exception:
        pass
    op.drop_index("ix_ews_follow_ups_created_at", table_name="ews_follow_ups")
    op.drop_index("ix_ews_follow_ups_student_id", table_name="ews_follow_ups")
    op.drop_table("ews_follow_ups")
    op.drop_index("ix_user_permission_grant_user", table_name="user_permission_grants")
    op.drop_table("user_permission_grants")
    op.drop_index("ix_laborant_lab_lab_id", table_name="laborant_lab_assignments")
    op.drop_table("laborant_lab_assignments")
    try:
        op.drop_column("laboratories", "display_pin_updated_at")
    except Exception:
        pass
    try:
        op.drop_column("laboratories", "display_pin_hash")
    except Exception:
        pass
