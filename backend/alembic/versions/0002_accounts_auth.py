"""accounts/auth

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-09

Pins the database to UTC, creates the citext extension and the shared
set_updated_at() trigger function, and creates accounts, users, sessions,
api_keys, auth_tokens.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TS = sa.DateTime(timezone=True)
UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    conn = op.get_bind()
    db_name = conn.execute(sa.text("SELECT current_database()")).scalar()
    op.execute(sa.text(f'ALTER DATABASE "{db_name}" SET timezone TO \'UTC\''))

    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$
        """
    )

    op.create_table(
        "accounts",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("plan", sa.Text(), nullable=False, server_default=sa.text("'launch'")),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("plan IN ('launch')", name="plan"),
    )
    op.execute(
        "CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON accounts "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("email_verified_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], ondelete="CASCADE", name="fk_users_account_id_accounts"
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_account_id", "users", ["account_id"])
    op.execute(
        "CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON users "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("last_seen_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name="fk_sessions_user_id_users"
        ),
        sa.CheckConstraint("id ~ '^[0-9a-f]{64}$'", name="id_format"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    op.create_table(
        "api_keys",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("prefix", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column(
            "scopes", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("last_used_at", TS, nullable=True),
        sa.Column("revoked_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], ondelete="CASCADE", name="fk_api_keys_account_id_accounts"
        ),
        sa.UniqueConstraint("prefix", name="uq_api_keys_prefix"),
    )
    op.create_index("ix_api_keys_account_id", "api_keys", ["account_id"])

    op.create_table(
        "auth_tokens",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("used_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name="fk_auth_tokens_user_id_users"
        ),
        sa.CheckConstraint(
            "purpose IN ('verify_email', 'reset_password')", name="purpose"
        ),
        sa.UniqueConstraint("token_hash", name="uq_auth_tokens_token_hash"),
    )
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"])
    op.create_index("ix_auth_tokens_expires_at", "auth_tokens", ["expires_at"])


def downgrade() -> None:
    op.drop_table("auth_tokens")
    op.drop_table("api_keys")
    op.drop_table("sessions")

    op.execute("DROP TRIGGER IF EXISTS trg_set_updated_at ON users")
    op.drop_table("users")

    op.execute("DROP TRIGGER IF EXISTS trg_set_updated_at ON accounts")
    op.drop_table("accounts")

    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    op.execute("DROP EXTENSION IF EXISTS citext")

    conn = op.get_bind()
    db_name = conn.execute(sa.text("SELECT current_database()")).scalar()
    op.execute(sa.text(f'ALTER DATABASE "{db_name}" RESET timezone'))
