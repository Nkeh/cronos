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
    Numeric,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    column,
    text,
)
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Monitor(Base):
    __tablename__ = "monitors"
    __table_args__ = (
        CheckConstraint("url ~* '^https?://' AND length(url) <= 2048", name="url_format"),
        CheckConstraint("method IN ('GET', 'HEAD')", name="method"),
        CheckConstraint(
            "expected_status ~ '^(2xx|[1-5][0-9]{2})$'", name="expected_status_format"
        ),
        CheckConstraint("interval_seconds >= 30", name="interval_floor"),
        CheckConstraint(
            "timeout_seconds BETWEEN 1 AND 60 AND timeout_seconds < interval_seconds",
            name="timeout_range",
        ),
        CheckConstraint("confirm_threshold BETWEEN 1 AND 10", name="confirm_threshold_range"),
        CheckConstraint("consecutive_failures >= 0", name="consecutive_failures_nonneg"),
        CheckConstraint("status IN ('new', 'up', 'down', 'paused')", name="status"),
        CheckConstraint(
            "(status = 'paused') = (NOT is_active)", name="paused_matches_active"
        ),
        UniqueConstraint("account_id", "id", name="uq_monitors_account_id_id"),
        Index(
            "ix_monitors_next_check_at",
            "next_check_at",
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'GET'"))
    expected_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'2xx'")
    )
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("10"))
    confirm_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("2")
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    next_check_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'new'"))
    last_checked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    status_changed_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("now()")
    )
    ewma_mean: Mapped[float | None] = mapped_column(DOUBLE_PRECISION, nullable=True)
    ewma_var: Mapped[float | None] = mapped_column(DOUBLE_PRECISION, nullable=True)
    ewma_n: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    anomaly_since: Mapped[datetime | None] = mapped_column(nullable=True)
    flapping_since: Mapped[datetime | None] = mapped_column(nullable=True)
    muted_until: Mapped[datetime | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))


class CheckResult(Base):
    __tablename__ = "check_results"
    __table_args__ = (
        CheckConstraint(
            "status_code IS NULL OR status_code BETWEEN 100 AND 599", name="status_code_range"
        ),
        CheckConstraint(
            "response_time_ms IS NULL OR response_time_ms >= 0", name="response_time_nonneg"
        ),
        CheckConstraint(
            "error_kind IS NULL OR error_kind IN "
            "('http_status', 'timeout', 'connection', 'dns', 'tls', 'redirects', 'blocked')",
            name="error_kind_allowed",
        ),
        Index(
            "ix_check_results_monitor_id_checked_at",
            "monitor_id",
            column("checked_at").desc(),
        ),
        Index(
            "ix_check_results_checked_at_brin",
            "checked_at",
            postgresql_using="brin",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    monitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False
    )
    checked_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
    scheduled_for: Mapped[datetime | None] = mapped_column(nullable=True)
    region: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'eu-1'"))
    is_up: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    suppressed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class LatencyHourly(Base):
    __tablename__ = "latency_hourly"
    __table_args__ = (
        PrimaryKeyConstraint("monitor_id", "hour", name="pk_latency_hourly"),
        CheckConstraint("checks >= 0", name="checks_nonneg"),
        CheckConstraint("up_checks >= 0 AND up_checks <= checks", name="up_checks_le_checks"),
    )

    monitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False
    )
    hour: Mapped[datetime] = mapped_column(nullable=False)
    checks: Mapped[int] = mapped_column(Integer, nullable=False)
    up_checks: Mapped[int] = mapped_column(Integer, nullable=False)
    min_ms: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    avg_ms: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    p95_ms: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    max_ms: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
