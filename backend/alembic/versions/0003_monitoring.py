"""monitoring

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-09

Creates monitors, heartbeats, check_results, heartbeat_pings, including the
partial indexes the runner's claim query and sweep query depend on.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TS = sa.DateTime(timezone=True)
UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "monitors",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False, server_default=sa.text("'GET'")),
        sa.Column("expected_status", sa.Text(), nullable=False, server_default=sa.text("'2xx'")),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("confirm_threshold", sa.Integer(), nullable=False, server_default=sa.text("2")),
        sa.Column(
            "consecutive_failures", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("next_check_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'new'")),
        sa.Column("last_checked_at", TS, nullable=True),
        sa.Column("status_changed_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("ewma_mean", postgresql.DOUBLE_PRECISION(), nullable=True),
        sa.Column("ewma_var", postgresql.DOUBLE_PRECISION(), nullable=True),
        sa.Column("ewma_n", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("anomaly_since", TS, nullable=True),
        sa.Column("flapping_since", TS, nullable=True),
        sa.Column("muted_until", TS, nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            ondelete="CASCADE",
            name="fk_monitors_account_id_accounts",
        ),
        sa.CheckConstraint(
            "url ~* '^https?://' AND length(url) <= 2048", name="url_format"
        ),
        sa.CheckConstraint("method IN ('GET', 'HEAD')", name="method"),
        sa.CheckConstraint(
            "expected_status ~ '^(2xx|[1-5][0-9]{2})$'",
            name="expected_status_format",
        ),
        sa.CheckConstraint("interval_seconds >= 30", name="interval_floor"),
        sa.CheckConstraint(
            "timeout_seconds BETWEEN 1 AND 60 AND timeout_seconds < interval_seconds",
            name="timeout_range",
        ),
        sa.CheckConstraint(
            "confirm_threshold BETWEEN 1 AND 10", name="confirm_threshold_range"
        ),
        sa.CheckConstraint(
            "consecutive_failures >= 0", name="consecutive_failures_nonneg"
        ),
        sa.CheckConstraint("status IN ('new', 'up', 'down', 'paused')", name="status"),
        sa.CheckConstraint(
            "(status = 'paused') = (NOT is_active)", name="paused_matches_active"
        ),
        sa.UniqueConstraint("account_id", "id", name="uq_monitors_account_id_id"),
    )
    op.create_index(
        "ix_monitors_next_check_at",
        "monitors",
        ["next_check_at"],
        postgresql_where=sa.text("is_active"),
    )
    op.execute(
        "CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON monitors "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    op.create_table(
        "heartbeats",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("period_seconds", sa.Integer(), nullable=False),
        sa.Column("grace_seconds", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'new'")),
        sa.Column("last_ping_at", TS, nullable=True),
        sa.Column("last_ping_kind", sa.Text(), nullable=True),
        sa.Column("status_changed_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("flapping_since", TS, nullable=True),
        sa.Column("muted_until", TS, nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            ondelete="CASCADE",
            name="fk_heartbeats_account_id_accounts",
        ),
        sa.CheckConstraint("slug ~ '^[A-Za-z0-9_-]{22}$'", name="slug_format"),
        sa.CheckConstraint("period_seconds >= 60", name="period_floor"),
        sa.CheckConstraint("grace_seconds >= 0", name="grace_nonneg"),
        sa.CheckConstraint(
            "status IN ('new', 'up', 'missed', 'failed', 'paused')", name="status"
        ),
        sa.CheckConstraint(
            "last_ping_kind IS NULL OR last_ping_kind IN ('success', 'fail')",
            name="last_ping_kind",
        ),
        sa.CheckConstraint(
            "(status = 'paused') = (NOT is_active)", name="paused_matches_active"
        ),
        sa.UniqueConstraint("slug", name="uq_heartbeats_slug"),
        sa.UniqueConstraint("account_id", "id", name="uq_heartbeats_account_id_id"),
    )
    op.create_index(
        "ix_heartbeats_last_ping_at",
        "heartbeats",
        ["last_ping_at"],
        postgresql_where=sa.text("is_active AND status = 'up'"),
    )
    op.execute(
        "CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON heartbeats "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    op.create_table(
        "check_results",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("monitor_id", UUID, nullable=False),
        sa.Column("checked_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("region", sa.Text(), nullable=False, server_default=sa.text("'eu-1'")),
        sa.Column("is_up", sa.Boolean(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("timings", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("suppressed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.ForeignKeyConstraint(
            ["monitor_id"],
            ["monitors.id"],
            ondelete="CASCADE",
            name="fk_check_results_monitor_id_monitors",
        ),
        sa.CheckConstraint(
            "status_code IS NULL OR status_code BETWEEN 100 AND 599",
            name="status_code_range",
        ),
        sa.CheckConstraint(
            "response_time_ms IS NULL OR response_time_ms >= 0",
            name="response_time_nonneg",
        ),
    )
    op.create_index(
        "ix_check_results_monitor_id_checked_at",
        "check_results",
        ["monitor_id", sa.text("checked_at DESC")],
    )
    op.create_index(
        "ix_check_results_checked_at_brin",
        "check_results",
        ["checked_at"],
        postgresql_using="brin",
    )

    op.create_table(
        "heartbeat_pings",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("heartbeat_id", UUID, nullable=False),
        sa.Column("received_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("ip_hash", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["heartbeat_id"],
            ["heartbeats.id"],
            ondelete="CASCADE",
            name="fk_heartbeat_pings_heartbeat_id_heartbeats",
        ),
        sa.CheckConstraint("kind IN ('success', 'fail')", name="kind"),
        sa.CheckConstraint(
            "user_agent IS NULL OR length(user_agent) <= 256",
            name="user_agent_length",
        ),
    )
    op.create_index(
        "ix_heartbeat_pings_heartbeat_id_received_at",
        "heartbeat_pings",
        ["heartbeat_id", sa.text("received_at DESC")],
    )
    op.create_index(
        "ix_heartbeat_pings_received_at_brin",
        "heartbeat_pings",
        ["received_at"],
        postgresql_using="brin",
    )


def downgrade() -> None:
    op.drop_table("heartbeat_pings")
    op.drop_table("check_results")

    op.execute("DROP TRIGGER IF EXISTS trg_set_updated_at ON heartbeats")
    op.drop_table("heartbeats")

    op.execute("DROP TRIGGER IF EXISTS trg_set_updated_at ON monitors")
    op.drop_table("monitors")
