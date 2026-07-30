"""add Scholens AccessKeys

Revision ID: b12d7d620e91
Revises: 7cd98485be13
Create Date: 2026-07-30 21:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b12d7d620e91"
down_revision: str | None = "7cd98485be13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "access_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("secret_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=20), nullable=False),
        sa.Column("permissions", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(name) BETWEEN 1 AND 80 AND name = btrim(name)",
            name="ck_access_keys_name",
        ),
        sa.CheckConstraint(
            "secret_hash ~ '^[0-9a-f]{64}$'",
            name="ck_access_keys_secret_hash",
        ),
        sa.CheckConstraint(
            "length(key_prefix) = 20",
            name="ck_access_keys_key_prefix",
        ),
        sa.CheckConstraint(
            "permissions IN ("
            "ARRAY['read']::text[], "
            "ARRAY['write']::text[], "
            "ARRAY['delete']::text[], "
            "ARRAY['read','write']::text[], "
            "ARRAY['read','delete']::text[], "
            "ARRAY['write','delete']::text[], "
            "ARRAY['read','write','delete']::text[]"
            ")",
            name="ck_access_keys_permissions",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="ck_access_keys_expiration",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_access_keys_revoked_at",
        ),
        sa.CheckConstraint(
            "last_used_at IS NULL OR last_used_at >= created_at",
            name="ck_access_keys_last_used_at",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="scholens",
    )
    op.create_index(
        "uq_access_keys_secret_hash",
        "access_keys",
        ["secret_hash"],
        unique=True,
        schema="scholens",
    )
    op.execute(
        "CREATE INDEX ix_access_keys_user_created "
        "ON scholens.access_keys (user_id, created_at DESC, id DESC)"
    )
    op.create_index(
        "ix_access_keys_user_revoked",
        "access_keys",
        ["user_id", "revoked_at"],
        unique=False,
        schema="scholens",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_access_keys_user_revoked",
        table_name="access_keys",
        schema="scholens",
    )
    op.drop_index(
        "ix_access_keys_user_created",
        table_name="access_keys",
        schema="scholens",
    )
    op.drop_index(
        "uq_access_keys_secret_hash",
        table_name="access_keys",
        schema="scholens",
    )
    op.drop_table("access_keys", schema="scholens")
