"""add persistent conversation paper context

Revision ID: 718cef86ad30
Revises: f6c2b752174e
Create Date: 2026-07-30 14:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "718cef86ad30"
down_revision: str | None = "f6c2b752174e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "paper_context_kind",
            sa.String(length=16),
            nullable=False,
            server_default="selection",
        ),
        schema="scholens",
    )
    op.create_check_constraint(
        "ck_conversations_paper_context_kind",
        "conversations",
        "paper_context_kind IN ('library', 'selection')",
        schema="scholens",
    )
    op.execute(
        "UPDATE scholens.conversations SET paper_context_kind = "
        "CASE WHEN scope_type = 'global' THEN 'library' ELSE 'selection' END"
    )
    op.create_table(
        "conversation_context_projects",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
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
            ["conversation_id"], ["scholens.conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["scholens.projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("conversation_id", "project_id"),
        schema="scholens",
    )
    op.create_index(
        op.f("ix_scholens_conversation_context_projects_project_id"),
        "conversation_context_projects",
        ["project_id"],
        unique=False,
        schema="scholens",
    )
    op.create_table(
        "conversation_context_documents",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
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
            ["conversation_id"], ["scholens.conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["scholens.documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("conversation_id", "document_id"),
        schema="scholens",
    )
    op.create_index(
        op.f("ix_scholens_conversation_context_documents_document_id"),
        "conversation_context_documents",
        ["document_id"],
        unique=False,
        schema="scholens",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_scholens_conversation_context_documents_document_id"),
        table_name="conversation_context_documents",
        schema="scholens",
    )
    op.drop_table("conversation_context_documents", schema="scholens")
    op.drop_index(
        op.f("ix_scholens_conversation_context_projects_project_id"),
        table_name="conversation_context_projects",
        schema="scholens",
    )
    op.drop_table("conversation_context_projects", schema="scholens")
    op.drop_constraint(
        "ck_conversations_paper_context_kind",
        "conversations",
        schema="scholens",
        type_="check",
    )
    op.drop_column("conversations", "paper_context_kind", schema="scholens")
