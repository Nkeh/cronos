from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Integer, Text, text
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ApiAlive(Base):
    __tablename__ = "api_alive"

    instance_id: Mapped[str] = mapped_column(Text, primary_key=True)
    last_alive_at: Mapped[datetime] = mapped_column(nullable=False)


class RunnerState(Base):
    __tablename__ = "runner_state"
    __table_args__ = (
        CheckConstraint("in_flight >= 0", name="in_flight_nonneg"),
        CheckConstraint("lag_seconds >= 0", name="lag_seconds_nonneg"),
    )

    runner_id: Mapped[str] = mapped_column(Text, primary_key=True)
    last_tick_at: Mapped[datetime] = mapped_column(nullable=False)
    in_flight: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    lag_seconds: Mapped[float] = mapped_column(
        DOUBLE_PRECISION, nullable=False, server_default=text("0")
    )
    canary_ok: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )


class SystemState(Base):
    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[datetime] = mapped_column(nullable=False)
