from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StatusPage(Base):
    __tablename__ = "status_pages"
    __table_args__ = (
        CheckConstraint(
            "slug ~ '^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$'", name="slug_format"
        ),
        CheckConstraint(
            "is_public OR access_token_hash IS NOT NULL", name="access_token_required"
        ),
        UniqueConstraint("account_id", "id", name="uq_status_pages_account_id_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    access_token_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    snapshot_at: Mapped[datetime | None] = mapped_column(nullable=True)
    snapshot_dirty: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))


class StatusPageItem(Base):
    __tablename__ = "status_page_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id", "status_page_id"],
            ["status_pages.account_id", "status_pages.id"],
            ondelete="CASCADE",
            name="fk_status_page_items_account_id_status_page_id_status_pages",
        ),
        ForeignKeyConstraint(
            ["account_id", "monitor_id"],
            ["monitors.account_id", "monitors.id"],
            ondelete="CASCADE",
            name="fk_status_page_items_account_id_monitor_id_monitors",
        ),
        ForeignKeyConstraint(
            ["account_id", "heartbeat_id"],
            ["heartbeats.account_id", "heartbeats.id"],
            ondelete="CASCADE",
            name="fk_status_page_items_account_id_heartbeat_id_heartbeats",
        ),
        CheckConstraint(
            "num_nonnulls(monitor_id, heartbeat_id) = 1", name="exactly_one_subject"
        ),
        UniqueConstraint(
            "status_page_id",
            "position",
            name="uq_status_page_items_page_position",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "uq_status_page_items_page_monitor",
            "status_page_id",
            "monitor_id",
            unique=True,
            postgresql_where=text("monitor_id IS NOT NULL"),
        ),
        Index(
            "uq_status_page_items_page_heartbeat",
            "status_page_id",
            "heartbeat_id",
            unique=True,
            postgresql_where=text("heartbeat_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    status_page_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    monitor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    heartbeat_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
