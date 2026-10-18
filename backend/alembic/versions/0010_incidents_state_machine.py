"""incidents state machine

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-16

Day 8: wires the confirmation/re-check/canary state machine on top of the already-migrated
(Day 2) incidents/notifications schema.

- monitors.failing_since: set when consecutive_failures goes 0 -> 1 (to the probe's own start
  time, never write-time now()), cleared on success. Lets an incident's started_at name the
  moment the target actually started failing, not the moment the threshold was confirmed.
- monitors.last_state_at: the probe start time of the last result actually applied to the state
  machine (the stale-result watermark). NOT NULL with server_default now() so every existing row
  gets a sane starting value and the "last_state_at IS NULL" branch in the state machine's
  freshness check is only ever hit in tests that construct a row explicitly without it.
- incidents.resolved_reason: recovered | paused | edited. NOT NULL iff resolved_at IS NOT NULL.
- runner_state.canary_ok: written every tick from the runner's own canary-round outcome.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "monitors", sa.Column("failing_since", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "monitors",
        sa.Column(
            "last_state_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.add_column("incidents", sa.Column("resolved_reason", sa.Text(), nullable=True))
    # Backfill before the CHECK below: every incident resolved before today only ever went
    # through the "recovered" path (pause/edit resolution didn't exist until Day 8).
    op.execute(
        "UPDATE incidents SET resolved_reason = 'recovered' WHERE resolved_at IS NOT NULL"
    )
    op.create_check_constraint(
        "resolved_reason_matches_resolved",
        "incidents",
        "(resolved_reason IS NOT NULL) = (resolved_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "resolved_reason_allowed",
        "incidents",
        "resolved_reason IS NULL OR resolved_reason IN ('recovered', 'paused', 'edited')",
    )

    op.add_column(
        "runner_state",
        sa.Column("canary_ok", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("runner_state", "canary_ok")
    op.drop_constraint("resolved_reason_allowed", "incidents", type_="check")
    op.drop_constraint("resolved_reason_matches_resolved", "incidents", type_="check")
    op.drop_column("incidents", "resolved_reason")
    op.drop_column("monitors", "last_state_at")
    op.drop_column("monitors", "failing_since")
