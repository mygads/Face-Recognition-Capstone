"""drop attendance_corrections (fitur koreksi dihapus; guru/aslab ubah langsung)

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
"""

from __future__ import annotations

from typing import Union

from alembic import op

revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, None] = "c7d8e9f0a1b2"


def upgrade() -> None:
    op.drop_table("attendance_corrections")


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade tidak didukung: tabel attendance_corrections sudah dihapus "
        "bersama fiturnya."
    )
