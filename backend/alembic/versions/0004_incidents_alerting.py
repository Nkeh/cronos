"""incidents/alerting

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-09

Creates incidents, notification_channels, monitor_channels,
heartbeat_channels, notifications (the outbox). Composite
(account_id, subject_id) foreign keys make cross-account links impossible
at the database level.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TS = sa.DateTime(timezone=True)
UUID = postgresql.UUID(as_uuid=True)

MONITOR_CAUSES = "('http_status', 'timeout', 'connection', 'dns', 'tls', 'redirects', 'blocked')"
HEARTBEAT_CAUSES = "('heartbeat_missed', 'heartbeat_fail')"
CAUSES = "('http_status', 'timeout', 'connection', 'dns', 'tls', 'redirects', 'blocked', 'heartbeat_missed', 'heartbeat_fail')"


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("monitor_id", UUID, nullable=True),
        sa.Column("heartbeat_id", UUID, nullable=True),
        sa.Column("started_at", TS, nullable=False),
        sa.Column("confirmed_at", TS, nullable=True),
        sa.Column("resolved_at", TS, nullable=True),
        sa.Column("cause", sa.Text(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("acknowledged_at", TS, nullable=True),
        sa.Column("acknowledged_by", UUID, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            ondelete="CASCADE",
            name="fk_incidents_account_id_accounts",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "monitor_id"],
            ["monitors.account_id", "monitors.id"],
            ondelete="CASCADE",
            name="fk_incidents_account_id_monitor_id_monitors",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "heartbeat_id"],
            ["heartbeats.account_id", "heartbeats.id"],
            ondelete="CASCADE",
            name="fk_incidents_account_id_heartbeat_id_heartbeats",
        ),
        sa.ForeignKeyConstraint(
            ["acknowledged_by"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_incidents_acknowledged_by_users",
        ),
        sa.CheckConstraint(
            "num_nonnulls(monitor_id, heartbeat_id) = 1", name="exactly_one_subject"
        ),
        sa.CheckConstraint(f"cause IN {CAUSES}", name="cause"),
        sa.CheckConstraint(
            f"(monitor_id IS NOT NULL AND cause IN {MONITOR_CAUSES}) "
            f"OR (heartbeat_id IS NOT NULL AND cause IN {HEARTBEAT_CAUSES})",
            name="cause_matches_subject",
        ),
        sa.CheckConstraint(
            "confirmed_at IS NULL OR confirmed_at >= started_at",
            name="confirmed_after_started",
        ),
        sa.CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= started_at",
            name="resolved_after_started",
        ),
        sa.UniqueConstraint("account_id", "id", name="uq_incidents_account_id_id"),
    )
    op.create_index(
        "uq_incidents_open_monitor",
        "incidents",
        ["monitor_id"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.create_index(
        "uq_incidents_open_heartbeat",
        "incidents",
        ["heartbeat_id"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.create_index(
        "ix_incidents_account_id_started_at",
        "incidents",
        ["account_id", sa.text("started_at DESC")],
    )

    op.create_table(
        "notification_channels",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("secret", sa.LargeBinary(), nullable=True),
        sa.Column("verified_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            ondelete="CASCADE",
            name="fk_notification_channels_account_id_accounts",
        ),
        sa.CheckConstraint(
            "kind IN ('email', 'webhook')", name="kind"
        ),
        sa.CheckConstraint(
            "kind <> 'webhook' OR secret IS NOT NULL",
            name="webhook_secret_required",
        ),
        sa.UniqueConstraint(
            "account_id", "id", name="uq_notification_channels_account_id_id"
        ),
    )
    op.execute(
        "CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON notification_channels "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    op.create_table(
        "monitor_channels",
        sa.Column("monitor_id", UUID, nullable=False),
        sa.Column("channel_id", UUID, nullable=False),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("monitor_id", "channel_id", name="pk_monitor_channels"),
        sa.ForeignKeyConstraint(
            ["account_id", "monitor_id"],
            ["monitors.account_id", "monitors.id"],
            ondelete="CASCADE",
            name="fk_monitor_channels_account_id_monitor_id_monitors",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "channel_id"],
            ["notification_channels.account_id", "notification_channels.id"],
            ondelete="CASCADE",
            name="fk_monitor_channels_account_id_channel_id_notif_channels",
        ),
    )
    op.create_index("ix_monitor_channels_channel_id", "monitor_channels", ["channel_id"])

    op.create_table(
        "heartbeat_channels",
        sa.Column("heartbeat_id", UUID, nullable=False),
        sa.Column("channel_id", UUID, nullable=False),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("heartbeat_id", "channel_id", name="pk_heartbeat_channels"),
        sa.ForeignKeyConstraint(
            ["account_id", "heartbeat_id"],
            ["heartbeats.account_id", "heartbeats.id"],
            ondelete="CASCADE",
            name="fk_heartbeat_channels_account_id_heartbeat_id_heartbeats",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "channel_id"],
            ["notification_channels.account_id", "notification_channels.id"],
            ondelete="CASCADE",
            name="fk_heartbeat_channels_account_id_channel_id_notif_channels",
        ),
    )
    op.create_index("ix_heartbeat_channels_channel_id", "heartbeat_channels", ["channel_id"])

    op.create_table(
        "notifications",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("incident_id", UUID, nullable=True),
        sa.Column("channel_id", UUID, nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("next_attempt_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("sent_at", TS, nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            ondelete="CASCADE",
            name="fk_notifications_account_id_accounts",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "channel_id"],
            ["notification_channels.account_id", "notification_channels.id"],
            ondelete="CASCADE",
            name="fk_notifications_account_id_channel_id_notif_channels",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "incident_id"],
            ["incidents.account_id", "incidents.id"],
            ondelete="CASCADE",
            name="fk_notifications_account_id_incident_id_incidents",
        ),
        sa.CheckConstraint(
            "event IN ('opened', 'resolved', 'fail_ping', 'flapping', 'cap_reached')",
            name="event",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'failed', 'suppressed')",
            name="status",
        ),
        sa.CheckConstraint("attempts >= 0", name="attempts_nonneg"),
    )
    op.create_index(
        "ix_notifications_next_attempt_at",
        "notifications",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_notifications_channel_id_created_at",
        "notifications",
        ["channel_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("heartbeat_channels")
    op.drop_table("monitor_channels")

    op.execute("DROP TRIGGER IF EXISTS trg_set_updated_at ON notification_channels")
    op.drop_table("notification_channels")

    op.drop_table("incidents")
