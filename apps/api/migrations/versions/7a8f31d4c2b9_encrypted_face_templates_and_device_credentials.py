"""store encrypted face templates and provision device credentials

Revision ID: 7a8f31d4c2b9
Revises: f19c8d723a4e
Create Date: 2026-10-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7a8f31d4c2b9"
down_revision: Union[str, None] = "f19c8d723a4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("credential_hash", sa.String(64)))
    op.add_column(
        "devices", sa.Column("credential_expires_at", sa.DateTime(timezone=True))
    )
    op.add_column("devices", sa.Column("previous_credential_hash", sa.String(64)))
    op.add_column(
        "devices",
        sa.Column("previous_credential_expires_at", sa.DateTime(timezone=True)),
    )

    op.add_column(
        "face_templates",
        sa.Column("enrollment_batch_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.add_column("face_templates", sa.Column("embedding_ciphertext", sa.LargeBinary()))
    op.add_column("face_templates", sa.Column("encryption_key_id", sa.String(80)))
    op.add_column("face_templates", sa.Column("embedding_dimension", sa.SmallInteger()))
    op.execute(
        sa.text(
            "UPDATE face_templates SET enrollment_batch_id = id "
            "WHERE enrollment_batch_id IS NULL"
        )
    )
    # Existing rows contain metadata only and cannot serve as recognition templates.
    op.execute(
        sa.text(
            "UPDATE face_templates SET revoked_at = CURRENT_TIMESTAMP "
            "WHERE revoked_at IS NULL AND embedding_ciphertext IS NULL"
        )
    )
    op.alter_column(
        "face_templates", "enrollment_batch_id", existing_type=sa.Uuid(), nullable=False
    )

    op.drop_index(
        "uq_face_templates_active_student_model_version", table_name="face_templates"
    )
    op.create_index(
        "ix_face_templates_active_model_student",
        "face_templates",
        ["model_name", "model_version", "student_id"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_face_templates_enrollment_batch_id",
        "face_templates",
        ["enrollment_batch_id"],
        unique=False,
    )
    op.create_check_constraint(
        "active_template_has_encrypted_embedding",
        "face_templates",
        "revoked_at IS NOT NULL OR (embedding_ciphertext IS NOT NULL "
        "AND encryption_key_id IS NOT NULL AND embedding_dimension IS NOT NULL "
        "AND embedding_dimension > 0)",
    )
    op.create_check_constraint(
        "embedding_dimension_positive",
        "face_templates",
        "embedding_dimension IS NULL OR embedding_dimension > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "embedding_dimension_positive",
        "face_templates",
        type_="check",
    )
    op.drop_constraint(
        "active_template_has_encrypted_embedding",
        "face_templates",
        type_="check",
    )
    op.drop_index("ix_face_templates_enrollment_batch_id", table_name="face_templates")
    op.drop_index("ix_face_templates_active_model_student", table_name="face_templates")
    op.drop_column("face_templates", "embedding_dimension")
    op.drop_column("face_templates", "encryption_key_id")
    op.drop_column("face_templates", "embedding_ciphertext")
    op.drop_column("face_templates", "enrollment_batch_id")
    op.create_index(
        "uq_face_templates_active_student_model_version",
        "face_templates",
        ["student_id", "model_name", "model_version"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_column("devices", "previous_credential_expires_at")
    op.drop_column("devices", "previous_credential_hash")
    op.drop_column("devices", "credential_expires_at")
    op.drop_column("devices", "credential_hash")
