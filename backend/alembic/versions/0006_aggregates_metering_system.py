"""aggregates/metering/system

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-09

Creates latency_hourly, usage_events, api_alive, runner_state,
system_state. None of these five get the updated_at trigger.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TS = sa.DateTime(timezone=True)
UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "latency_hourly",
        sa.Column("monitor_id", UUID, nullable=False),
        sa.Column("hour", TS, nullable=False),
        sa.Column("checks", sa.Integer(), nullable=False),
        sa.Column("up_checks", sa.Integer(), nullable=False),
        sa.Column("min_ms", sa.Numeric(10, 2), nullable=True),
        sa.Column("avg_ms", sa.Numeric(10, 2), nullable=True),
        sa.Column("p95_ms", sa.Numeric(10, 2), nullable=True),
        sa.Column("max_ms", sa.Numeric(10, 2), nullable=True),
        sa.PrimaryKeyConstraint("monitor_id", "hour", name="pk_latency_hourly"),
        sa.ForeignKeyConstraint(
            ["monitor_id"],
            ["monitors.id"],
            ondelete="CASCADE",
            name="fk_latency_hourly_monitor_id_monitors",
        ),
        sa.CheckConstraint("checks >= 0", name="checks_nonneg"),
        sa.CheckConstraint(
            "up_checks >= 0 AND up_checks <= checks", name="up_checks_le_checks"
        ),
    )

    op.create_table(
        "usage_events",
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("account_id", "day", "kind", name="pk_usage_events"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            ondelete="CASCADE",
            name="fk_usage_events_account_id_accounts",
        ),
        sa.CheckConstraint("quantity >= 0", name="quantity_nonneg"),
    )

    op.create_table(
        "api_alive",
        sa.Column("instance_id", sa.Text(), primary_key=True),
        sa.Column("last_alive_at", TS, nullable=False),
    )

    op.create_table(
        "runner_state",
        sa.Column("runner_id", sa.Text(), primary_key=True),
        sa.Column("last_tick_at", TS, nullable=False),
        sa.Column("in_flight", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "lag_seconds", postgresql.DOUBLE_PRECISION(), nullable=False, server_default=sa.text("0")
        ),
        sa.CheckConstraint("in_flight >= 0", name="in_flight_nonneg"),
        sa.CheckConstraint("lag_seconds >= 0", name="lag_seconds_nonneg"),
    )

    op.create_table(
        "system_state",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", TS, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("system_state")
    op.drop_table("runner_state")
    op.drop_table("api_alive")
    op.drop_table("usage_events")
    op.drop_table("latency_hourly")
