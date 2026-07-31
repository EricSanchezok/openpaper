"""add user connector connections

Revision ID: 77a0c6af7e31
Revises: b12d7d620e91
Create Date: 2026-07-31 15:00:00+08:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "77a0c6af7e31"
down_revision: str | None = "b12d7d620e91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connector_connections",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("credential_ciphertext", sa.Text(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
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
            "provider IN ('anysearch', 'tavily', 'exa', 'firecrawl')",
            name="ck_connector_connections_provider",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "provider"),
        schema="scholens",
    )


def downgrade() -> None:
    op.drop_table("connector_connections", schema="scholens")
