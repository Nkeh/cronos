"""The one shared declarative Base and naming convention.

Every domain model imports only this module (never another domain's models),
so foreign keys that cross domain packages are written as plain strings
(e.g. ForeignKey("accounts.id")) and resolved by SQLAlchemy against
Base.metadata at mapper-configuration time, not at import time. That keeps
this package graph acyclic without any import-order tricks.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import MetaData, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # Every bare `Mapped[datetime]` column becomes timestamptz, matching the
    # migrations (sa.DateTime(timezone=True)) — otherwise the default mapping
    # (timestamp without time zone) would show up as drift against every
    # migration that creates a timestamp column.
    type_annotation_map = {
        datetime: TIMESTAMP(timezone=True),
    }
