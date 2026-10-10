"""status pages

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-09

Creates status_pages and status_page_items, including the deferrable
unique position constraint that lets a reorder swap two items' positions
inside one transaction.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TS = sa.DateTime(timezone=True)
UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "status_pages",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("access_token_hash", sa.Text(), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("snapshot_at", TS, nullable=True),
        sa.Column("snapshot_dirty", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            ondelete="CASCADE",
            name="fk_status_pages_account_id_accounts",
        ),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$'", name="slug_format"
        ),
        sa.CheckConstraint(
            "is_public OR access_token_hash IS NOT NULL",
            name="access_token_required",
        ),
        sa.UniqueConstraint("slug", name="uq_status_pages_slug"),
        sa.UniqueConstraint("account_id", "id", name="uq_status_pages_account_id_id"),
    )
    op.execute(
        "CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON status_pages "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    op.create_table(
        "status_page_items",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("status_page_id", UUID, nullable=False),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("monitor_id", UUID, nullable=True),
        sa.Column("heartbeat_id", UUID, nullable=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["account_id", "status_page_id"],
            ["status_pages.account_id", "status_pages.id"],
            ondelete="CASCADE",
            name="fk_status_page_items_account_id_status_page_id_status_pages",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "monitor_id"],
            ["monitors.account_id", "monitors.id"],
            ondelete="CASCADE",
            name="fk_status_page_items_account_id_monitor_id_monitors",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "heartbeat_id"],
            ["heartbeats.account_id", "heartbeats.id"],
            ondelete="CASCADE",
            name="fk_status_page_items_account_id_heartbeat_id_heartbeats",
        ),
        sa.CheckConstraint(
            "num_nonnulls(monitor_id, heartbeat_id) = 1",
            name="exactly_one_subject",
        ),
    )
    op.create_unique_constraint(
        "uq_status_page_items_page_position",
        "status_page_items",
        ["status_page_id", "position"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_index(
        "uq_status_page_items_page_monitor",
        "status_page_items",
        ["status_page_id", "monitor_id"],
        unique=True,
        postgresql_where=sa.text("monitor_id IS NOT NULL"),
    )
    op.create_index(
        "uq_status_page_items_page_heartbeat",
        "status_page_items",
        ["status_page_id", "heartbeat_id"],
        unique=True,
        postgresql_where=sa.text("heartbeat_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("status_page_items")

    op.execute("DROP TRIGGER IF EXISTS trg_set_updated_at ON status_pages")
    op.drop_table("status_pages")
