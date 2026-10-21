from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    column,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotificationChannel(Base):
    __tablename__ = "notification_channels"
    __table_args__ = (
        CheckConstraint("kind IN ('email', 'webhook')", name="kind"),
        CheckConstraint(
            "kind <> 'webhook' OR secret IS NOT NULL", name="webhook_secret_required"
        ),
        CheckConstraint("char_length(name) BETWEEN 1 AND 60", name="name_length"),
        UniqueConstraint("account_id", "id", name="uq_notification_channels_account_id_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    secret: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    is_default: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    verify_token_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    verify_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))


class MonitorChannel(Base):
    __tablename__ = "monitor_channels"
    __table_args__ = (
        PrimaryKeyConstraint("monitor_id", "channel_id", name="pk_monitor_channels"),
        ForeignKeyConstraint(
            ["account_id", "monitor_id"],
            ["monitors.account_id", "monitors.id"],
            ondelete="CASCADE",
            name="fk_monitor_channels_account_id_monitor_id_monitors",
        ),
        ForeignKeyConstraint(
            ["account_id", "channel_id"],
            ["notification_channels.account_id", "notification_channels.id"],
            ondelete="CASCADE",
            name="fk_monitor_channels_account_id_channel_id_notif_channels",
        ),
        Index("ix_monitor_channels_channel_id", "channel_id"),
    )

    monitor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    channel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))


class HeartbeatChannel(Base):
    __tablename__ = "heartbeat_channels"
    __table_args__ = (
        PrimaryKeyConstraint("heartbeat_id", "channel_id", name="pk_heartbeat_channels"),
        ForeignKeyConstraint(
            ["account_id", "heartbeat_id"],
            ["heartbeats.account_id", "heartbeats.id"],
            ondelete="CASCADE",
            name="fk_heartbeat_channels_account_id_heartbeat_id_heartbeats",
        ),
        ForeignKeyConstraint(
            ["account_id", "channel_id"],
            ["notification_channels.account_id", "notification_channels.id"],
            ondelete="CASCADE",
            name="fk_heartbeat_channels_account_id_channel_id_notif_channels",
        ),
        Index("ix_heartbeat_channels_channel_id", "channel_id"),
    )

    heartbeat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    channel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))


class Notification(Base):
    """The outbox."""

    __tablename__ = "notifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id", "channel_id"],
            ["notification_channels.account_id", "notification_channels.id"],
            ondelete="CASCADE",
            name="fk_notifications_account_id_channel_id_notif_channels",
        ),
        ForeignKeyConstraint(
            ["account_id", "incident_id"],
            ["incidents.account_id", "incidents.id"],
            ondelete="CASCADE",
            name="fk_notifications_account_id_incident_id_incidents",
        ),
        CheckConstraint(
            "event IN ('opened', 'resolved', 'fail_ping', 'flapping', 'cap_reached')",
            name="event",
        ),
        CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'failed', 'suppressed')", name="status"
        ),
        CheckConstraint("attempts >= 0", name="attempts_nonneg"),
        Index(
            "ix_notifications_next_attempt_at",
            "next_attempt_at",
            postgresql_where=text("status IN ('pending', 'sending')"),
        ),
        Index(
            "ix_notifications_channel_id_created_at",
            "channel_id",
            column("created_at").desc(),
        ),
        Index(
            "ix_notifications_account_id_sent_at",
            "account_id",
            "sent_at",
            postgresql_where=text("status = 'sent'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    channel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("now()")
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)


class NotificationAttempt(Base):
    """One row per delivery attempt (FR-6.6's delivery log). bigint identity PK -- a deviation
    from CLAUDE.md's stated bigint exceptions (check_results, heartbeat_pings), same rationale
    (high-volume, append-only), flagged in docs/progress/day-09.md."""

    __tablename__ = "notification_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["notification_id"],
            ["notifications.id"],
            ondelete="CASCADE",
            name="fk_notification_attempts_notification_id_notifications",
        ),
        CheckConstraint("outcome IN ('sent', 'retry', 'failed')", name="outcome"),
        Index(
            "ix_notification_attempts_notification_id_attempted_at",
            "notification_id",
            "attempted_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    notification_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
