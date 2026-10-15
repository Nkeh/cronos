"""check_results.scheduled_for

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-14

Adds check_results.scheduled_for (nullable timestamptz): the monitor's next_check_at
value at claim time, captured by the runner's claim CTE (SRS Section 7). Start lag =
checked_at - scheduled_for. Nullable permanently, not just as a backfill safety net --
pre-Day-6 rows and any future out-of-band inserts legitimately have no claim-time value.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "check_results", sa.Column("scheduled_for", sa.TIMESTAMP(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("check_results", "scheduled_for")
