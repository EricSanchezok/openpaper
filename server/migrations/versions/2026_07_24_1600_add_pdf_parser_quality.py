"""add PDF parser quality metadata

Revision ID: a49f2e7c1b0d
Revises: 59636e6aa2f2
Create Date: 2026-07-24 16:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a49f2e7c1b0d"
down_revision: Union[str, None] = "59636e6aa2f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "papers",
        sa.Column("parser_backend", sa.String(), nullable=True),
        schema="scholens",
    )
    op.add_column(
        "papers",
        sa.Column("parser_quality", sa.String(), nullable=True),
        schema="scholens",
    )
    op.add_column(
        "papers",
        sa.Column("parser_version", sa.String(), nullable=True),
        schema="scholens",
    )
    op.add_column(
        "papers",
        sa.Column("parser_warning_code", sa.String(), nullable=True),
        schema="scholens",
    )
    op.create_check_constraint(
        "ck_papers_parser_backend",
        "papers",
        "parser_backend IS NULL OR parser_backend IN ('mineru', 'pymupdf')",
        schema="scholens",
    )
    op.create_check_constraint(
        "ck_papers_parser_quality",
        "papers",
        "parser_quality IS NULL OR parser_quality IN ('full', 'text_only')",
        schema="scholens",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_papers_parser_quality",
        "papers",
        type_="check",
        schema="scholens",
    )
    op.drop_constraint(
        "ck_papers_parser_backend",
        "papers",
        type_="check",
        schema="scholens",
    )
    op.drop_column("papers", "parser_warning_code", schema="scholens")
    op.drop_column("papers", "parser_version", schema="scholens")
    op.drop_column("papers", "parser_quality", schema="scholens")
    op.drop_column("papers", "parser_backend", schema="scholens")
