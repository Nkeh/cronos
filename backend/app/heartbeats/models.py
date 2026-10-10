from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    column,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Heartbeat(Base):
    __tablename__ = "heartbeats"
    __table_args__ = (
        CheckConstraint("slug ~ '^[A-Za-z0-9_-]{22}$'", name="slug_format"),
        CheckConstraint("period_seconds >= 60", name="period_floor"),
        CheckConstraint("grace_seconds >= 0", name="grace_nonneg"),
        CheckConstraint(
            "status IN ('new', 'up', 'missed', 'failed', 'paused')", name="status"
        ),
        CheckConstraint(
            "last_ping_kind IS NULL OR last_ping_kind IN ('success', 'fail')",
            name="last_ping_kind",
        ),
        CheckConstraint(
            "(status = 'paused') = (NOT is_active)", name="paused_matches_active"
        ),
        UniqueConstraint("account_id", "id", name="uq_heartbeats_account_id_id"),
        Index(
            "ix_heartbeats_last_ping_at",
            "last_ping_at",
            postgresql_where=text("is_active AND status = 'up'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    period_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    grace_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'new'"))
    last_ping_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_ping_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_changed_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("now()")
    )
    flapping_since: Mapped[datetime | None] = mapped_column(nullable=True)
    muted_until: Mapped[datetime | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))


class HeartbeatPing(Base):
    __tablename__ = "heartbeat_pings"
    __table_args__ = (
        CheckConstraint("kind IN ('success', 'fail')", name="kind"),
        CheckConstraint(
            "user_agent IS NULL OR length(user_agent) <= 256", name="user_agent_length"
        ),
        Index(
            "ix_heartbeat_pings_heartbeat_id_received_at",
            "heartbeat_id",
            column("received_at").desc(),
        ),
        Index(
            "ix_heartbeat_pings_received_at_brin",
            "received_at",
            postgresql_using="brin",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    heartbeat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("heartbeats.id", ondelete="CASCADE"), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    ip_hash: Mapped[str] = mapped_column(Text, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
