"""spec 1:1 penugasan guru/laboratorium, kiosk, koreksi insiden, waktu datang

Revision ID: d5e6f7a8b9c0
Revises: f5a6b7c8d9e0, e49c72ab31d0, 2b8f61e4c0a7, 8d3a1f6c2b90, a7d4e9c20b61
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = (
    "f5a6b7c8d9e0",
    "e49c72ab31d0",
    "2b8f61e4c0a7",
    "8d3a1f6c2b90",
    "a7d4e9c20b61",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from alembic import op

    # teacher_class_assignments
    op.create_table(
        "teacher_class_assignments",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("class_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column(
            "is_substitute",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["assigned_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("user_id", "class_id"),
    )
    op.create_index(
        "ix_teacher_class_class_id", "teacher_class_assignments", ["class_id"]
    )
    # class_laboratories
    op.create_table(
        "class_laboratories",
        sa.Column("class_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["laboratory_id"], ["laboratories.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("class_id", "laboratory_id"),
    )
    op.create_index(
        "ix_class_lab_laboratory_id", "class_laboratories", ["laboratory_id"]
    )
    # kiosk_screens
    op.create_table(
        "kiosk_screens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("laboratory_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("camera_label", sa.String(120), nullable=True),
        sa.Column("pin_hash", sa.String(255), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["laboratory_id"], ["laboratories.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "device_id", "laboratory_id", name="uq_kiosk_screens_device_lab"
        ),
    )
    op.create_index("ix_kiosk_screens_device_id", "kiosk_screens", ["device_id"])
    op.create_index(
        "ix_kiosk_screens_laboratory_id", "kiosk_screens", ["laboratory_id"]
    )
    # attendance_records: occurred_at + rule_version
    op.add_column(
        "attendance_records",
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attendance_records", sa.Column("rule_version", sa.Integer(), nullable=True)
    )
    # attendance_corrections: incident_ref + partial uniques
    op.add_column(
        "attendance_corrections",
        sa.Column("incident_ref", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_attendance_corrections_incident_ref",
        "attendance_corrections",
        ["incident_ref"],
    )
    op.create_index(
        "uq_correction_pending_record",
        "attendance_corrections",
        ["attendance_record_id"],
        unique=True,
        postgresql_where=sa.text("decision_status = 'pending'"),
        sqlite_where=sa.text("decision_status = 'pending'"),
    )
    op.create_index(
        "uq_correction_pending_missing",
        "attendance_corrections",
        ["session_id", "student_id"],
        unique=True,
        postgresql_where=sa.text("decision_status = 'pending'"),
        sqlite_where=sa.text("decision_status = 'pending'"),
    )
    # ews_follow_ups: status + resolved_at
    op.add_column(
        "ews_follow_ups",
        sa.Column(
            "status", sa.String(16), server_default=sa.text("'open'"), nullable=False
        ),
    )
    op.add_column(
        "ews_follow_ups",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ews_follow_up_status", "ews_follow_ups", "status IN ('open', 'done')"
    )


def downgrade() -> None:
    from alembic import op

    try:
        op.drop_constraint("ews_follow_up_status", "ews_follow_ups", type_="check")
    except Exception:
        pass
    try:
        op.drop_column("ews_follow_ups", "resolved_at")
    except Exception:
        pass
    try:
        op.drop_column("ews_follow_ups", "status")
    except Exception:
        pass
    try:
        op.drop_index(
            "uq_correction_pending_missing",
            table_name="attendance_corrections",
        )
    except Exception:
        pass
    try:
        op.drop_index(
            "uq_correction_pending_record",
            table_name="attendance_corrections",
        )
    except Exception:
        pass
    try:
        op.drop_index(
            "ix_attendance_corrections_incident_ref",
            table_name="attendance_corrections",
        )
    except Exception:
        pass
    try:
        op.drop_column("attendance_corrections", "incident_ref")
    except Exception:
        pass
    try:
        op.drop_column("attendance_records", "rule_version")
    except Exception:
        pass
    try:
        op.drop_column("attendance_records", "occurred_at")
    except Exception:
        pass
    try:
        op.drop_index("ix_kiosk_screens_laboratory_id", table_name="kiosk_screens")
    except Exception:
        pass
    try:
        op.drop_index("ix_kiosk_screens_device_id", table_name="kiosk_screens")
    except Exception:
        pass
    try:
        op.drop_table("kiosk_screens")
    except Exception:
        pass
    try:
        op.drop_index("ix_class_lab_laboratory_id", table_name="class_laboratories")
    except Exception:
        pass
    try:
        op.drop_table("class_laboratories")
    except Exception:
        pass
    try:
        op.drop_index(
            "ix_teacher_class_class_id", table_name="teacher_class_assignments"
        )
    except Exception:
        pass
    try:
        op.drop_table("teacher_class_assignments")
    except Exception:
        pass
