"""allow privacy-redacted recognition event records

Revision ID: 91a4e8b6c2f0
Revises: 7a8f31d4c2b9
Create Date: 2026-10-02
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "91a4e8b6c2f0"
down_revision: Union[str, None] = "7a8f31d4c2b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("event_outcome", "recognition_events", type_="check")
    op.create_check_constraint(
        "event_outcome",
        "recognition_events",
        "outcome IN ('matched', 'ambiguous', 'no_match', 'error', 'redacted')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE recognition_events SET outcome = 'error' WHERE outcome = 'redacted'"
    )
    op.drop_constraint("event_outcome", "recognition_events", type_="check")
    op.create_check_constraint(
        "event_outcome",
        "recognition_events",
        "outcome IN ('matched', 'ambiguous', 'no_match', 'error')",
    )
