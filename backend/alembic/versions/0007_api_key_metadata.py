"""api key metadata

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-13

Adds api_keys.name (NOT NULL, 1-60 chars) and api_keys.created_by_user_id
(nullable FK -> users, ON DELETE SET NULL). SRS Section 5 omits both; Day 4
flags this as a deviation. name is added nullable, backfilled, then made
NOT NULL, so this is safe even if dev rows already exist.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("name", sa.Text(), nullable=True))
    op.execute(
        "UPDATE api_keys SET name = 'key-' || substr(id::text, 1, 8) WHERE name IS NULL"
    )
    op.alter_column("api_keys", "name", nullable=False)
    op.create_check_constraint("name_length", "api_keys", "length(name) BETWEEN 1 AND 60")

    op.add_column("api_keys", sa.Column("created_by_user_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_api_keys_created_by_user_id_users",
        "api_keys",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_api_keys_created_by_user_id_users", "api_keys", type_="foreignkey")
    op.drop_column("api_keys", "created_by_user_id")
    op.drop_constraint("name_length", "api_keys", type_="check")
    op.drop_column("api_keys", "name")
