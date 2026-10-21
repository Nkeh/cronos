"""notifier + channels

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-19

Day 9: the notifier drains the Day 8 outbox. This migration gives notification_channels what the
Channels API needs (a display name, a default-routing flag, an email-verification token) and adds
the per-attempt delivery log (FR-6.6) plus the two indexes the notifier/caps logic reads.

- notification_channels.name: NOT NULL, 1-60 chars. Backfilled for any pre-existing row (there are
  none in practice -- no channel-creation API has ever existed before today -- but the backfill
  keeps this migration correct regardless).
- notification_channels.is_default: routed to automatically on monitor creation (Day 9 hook).
- notification_channels.verify_token_hash/verify_expires_at: the email-verification flow's token,
  stored on the channel itself rather than reusing auth_tokens -- a channel's verification is
  scoped to the channel, not the account.
- notification_attempts: one row per delivery attempt (FR-6.6's delivery log). bigint identity PK,
  not UUID -- a deviation from CLAUDE.md's stated bigint exceptions (check_results,
  heartbeat_pings), same rationale (high-volume, append-only), flagged in docs/progress/day-09.md.
- ix_notifications_next_attempt_at widens from WHERE status='pending' to WHERE status IN
  ('pending','sending') -- the notifier's claim needs to find expired-lease 'sending' rows too
  (see app/notifier/claim.py), not just fresh 'pending' ones.
- ix_notifications_account_id_sent_at backs the daily per-account-per-kind cap count (FR-6.5).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TS = sa.DateTime(timezone=True)
UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column("notification_channels", sa.Column("name", sa.Text(), nullable=True))
    op.execute(
        "UPDATE notification_channels SET name = initcap(kind) || ' channel' WHERE name IS NULL"
    )
    op.alter_column("notification_channels", "name", nullable=False)
    op.create_check_constraint(
        "name_length", "notification_channels", "char_length(name) BETWEEN 1 AND 60"
    )
    op.add_column(
        "notification_channels",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "notification_channels", sa.Column("verify_token_hash", sa.Text(), nullable=True)
    )
    op.add_column(
        "notification_channels", sa.Column("verify_expires_at", TS, nullable=True)
    )

    op.create_table(
        "notification_attempts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("notification_id", UUID, nullable=False),
        sa.Column("attempted_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["notifications.id"],
            ondelete="CASCADE",
            name="fk_notification_attempts_notification_id_notifications",
        ),
        sa.CheckConstraint("outcome IN ('sent', 'retry', 'failed')", name="outcome"),
    )
    op.create_index(
        "ix_notification_attempts_notification_id_attempted_at",
        "notification_attempts",
        ["notification_id", "attempted_at"],
    )

    op.drop_index("ix_notifications_next_attempt_at", table_name="notifications")
    op.create_index(
        "ix_notifications_next_attempt_at",
        "notifications",
        ["next_attempt_at"],
        postgresql_where=sa.text("status IN ('pending', 'sending')"),
    )
    op.create_index(
        "ix_notifications_account_id_sent_at",
        "notifications",
        ["account_id", "sent_at"],
        postgresql_where=sa.text("status = 'sent'"),
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_account_id_sent_at", table_name="notifications")
    op.drop_index("ix_notifications_next_attempt_at", table_name="notifications")
    op.create_index(
        "ix_notifications_next_attempt_at",
        "notifications",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.drop_index(
        "ix_notification_attempts_notification_id_attempted_at",
        table_name="notification_attempts",
    )
    op.drop_table("notification_attempts")

    op.drop_column("notification_channels", "verify_expires_at")
    op.drop_column("notification_channels", "verify_token_hash")
    op.drop_column("notification_channels", "is_default")
    op.drop_constraint("name_length", "notification_channels", type_="check")
    op.drop_column("notification_channels", "name")
