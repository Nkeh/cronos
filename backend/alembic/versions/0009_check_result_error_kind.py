"""check_results.error_kind

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-15

Adds check_results.error_kind (nullable text, CHECK-constrained to a fixed vocabulary): the
probe's own classification of why a check failed (NULL on success). Lets incident/notification
copy (Day 8/9) and the UI distinguish "the target is slow" from "DNS is broken" from "we
blocked this as SSRF" without parsing the free-text error column.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("check_results", sa.Column("error_kind", sa.Text(), nullable=True))
    op.create_check_constraint(
        "error_kind_allowed",
        "check_results",
        "error_kind IS NULL OR error_kind IN "
        "('http_status', 'timeout', 'connection', 'dns', 'tls', 'redirects', 'blocked')",
    )


def downgrade() -> None:
    op.drop_constraint("error_kind_allowed", "check_results", type_="check")
    op.drop_column("check_results", "error_kind")
