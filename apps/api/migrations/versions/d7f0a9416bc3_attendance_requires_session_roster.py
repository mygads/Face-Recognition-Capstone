"""require attendance records to reference the session roster snapshot

Revision ID: d7f0a9416bc3
Revises: c621cc9d1ea9
Create Date: 2026-10-01
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "d7f0a9416bc3"
down_revision: Union[str, None] = "c621cc9d1ea9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Preserve existing attendance history by seeding its missing snapshot rows.
    op.execute(
        """
        INSERT INTO session_students (
            session_id,
            student_id,
            student_number_snapshot,
            full_name_snapshot,
            snapshot_taken_at
        )
        SELECT DISTINCT
            records.session_id,
            records.student_id,
            students.student_number,
            students.full_name,
            CURRENT_TIMESTAMP
        FROM attendance_records AS records
        JOIN students ON students.id = records.student_id
        ON CONFLICT (session_id, student_id) DO NOTHING
        """
    )
    op.create_foreign_key(
        "fk_attendance_records_session_roster",
        "attendance_records",
        "session_students",
        ["session_id", "student_id"],
        ["session_id", "student_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_attendance_records_session_roster",
        "attendance_records",
        type_="foreignkey",
    )
