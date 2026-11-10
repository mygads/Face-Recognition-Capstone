"""backfill occurred_at record wajah dari recognition event tertaut

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from alembic import op

    # Hanya record face_recognition yang punya event tertaut: waktu kejadian
    # diambil dari bukti event, BUKAN dari waktu simpan. Record manual/system
    # tanpa jam datang yang diketahui tetap NULL (ditampilkan tanpa durasi).
    op.execute(
        sa.text(
            """
            UPDATE attendance_records AS r
            SET occurred_at = e.occurred_at
            FROM recognition_events AS e
            WHERE r.recognition_event_id = e.id
              AND r.source = 'face_recognition'
              AND r.occurred_at IS NULL
              AND e.occurred_at IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    # Backfill tidak bisa dibatalkan secara selektif; biarkan apa adanya.
    pass
