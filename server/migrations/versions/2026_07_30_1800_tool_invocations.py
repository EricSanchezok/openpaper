"""add durable model tool invocation ledger

Revision ID: 7cd98485be13
Revises: 718cef86ad30
Create Date: 2026-07-30 18:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7cd98485be13"
down_revision: str | None = "718cef86ad30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_invocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("invocation_key", sa.String(length=512), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("arguments_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="completed",
            nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["auth.users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_id",
            "invocation_key",
            name="uq_tool_invocations_actor_key",
        ),
        schema="scholens",
    )
    op.create_index(
        op.f("ix_scholens_tool_invocations_actor_id"),
        "tool_invocations",
        ["actor_id"],
        unique=False,
        schema="scholens",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_scholens_tool_invocations_actor_id"),
        table_name="tool_invocations",
        schema="scholens",
    )
    op.drop_table("tool_invocations", schema="scholens")
