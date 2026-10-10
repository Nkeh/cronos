from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    column,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: incidents.cause — fixed list. The SRS never enumerates this. Monitor causes name the
#: specific probe failure (matches the probe/SSRF-guard failure modes in SRS §7/§13);
#: heartbeat causes stay generic since a heartbeat only ever "doesn't show up" one of two ways.
MONITOR_CAUSES = ("http_status", "timeout", "connection", "dns", "tls", "redirects", "blocked")
HEARTBEAT_CAUSES = ("heartbeat_missed", "heartbeat_fail")
CAUSES = MONITOR_CAUSES + HEARTBEAT_CAUSES


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id", "monitor_id"],
            ["monitors.account_id", "monitors.id"],
            ondelete="CASCADE",
            name="fk_incidents_account_id_monitor_id_monitors",
        ),
        ForeignKeyConstraint(
            ["account_id", "heartbeat_id"],
            ["heartbeats.account_id", "heartbeats.id"],
            ondelete="CASCADE",
            name="fk_incidents_account_id_heartbeat_id_heartbeats",
        ),
        CheckConstraint(
            "num_nonnulls(monitor_id, heartbeat_id) = 1", name="exactly_one_subject"
        ),
        CheckConstraint(f"cause IN {CAUSES!r}", name="cause"),
        CheckConstraint(
            f"(monitor_id IS NOT NULL AND cause IN {MONITOR_CAUSES!r}) "
            f"OR (heartbeat_id IS NOT NULL AND cause IN {HEARTBEAT_CAUSES!r})",
            name="cause_matches_subject",
        ),
        CheckConstraint(
            "confirmed_at IS NULL OR confirmed_at >= started_at", name="confirmed_after_started"
        ),
        CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= started_at", name="resolved_after_started"
        ),
        UniqueConstraint("account_id", "id", name="uq_incidents_account_id_id"),
        Index(
            "uq_incidents_open_monitor",
            "monitor_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
        Index(
            "uq_incidents_open_heartbeat",
            "heartbeat_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
        Index(
            "ix_incidents_account_id_started_at",
            "account_id",
            column("started_at").desc(),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    monitor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    heartbeat_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    cause: Mapped[str] = mapped_column(Text, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(nullable=True)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
