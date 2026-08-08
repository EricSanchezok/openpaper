"""expand parser_backend values

Revision ID: 3f9a1c7e5b2d
Revises: 77a0c6af7e31
Create Date: 2026-08-08 16:40:00.000000+00:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f9a1c7e5b2d"
down_revision: str | None = "77a0c6af7e31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Map legacy pymupdf rows and widen the parser_backend check constraint."""
    # Map historical PyMuPDF text-only rows to the upgraded local engine
    # semantics before the constraint accepts the new value set.
    op.execute(
        "UPDATE scholens.documents "
        "SET parser_backend = 'pymupdf4llm' "
        "WHERE parser_backend = 'pymupdf'"
    )
    op.drop_constraint(
        "ck_documents_parser_backend",
        "documents",
        schema="scholens",
        type_="check",
    )
    op.create_check_constraint(
        "ck_documents_parser_backend",
        "documents",
        "parser_backend IS NULL OR parser_backend IN ('mineru', 'pymupdf4llm', 'markitdown')",
        schema="scholens",
    )


def downgrade() -> None:
    """Restore the legacy parser_backend value set (dev data only)."""
    op.drop_constraint(
        "ck_documents_parser_backend",
        "documents",
        schema="scholens",
        type_="check",
    )
    op.execute(
        "UPDATE scholens.documents "
        "SET parser_backend = 'pymupdf' "
        "WHERE parser_backend IN ('pymupdf4llm', 'markitdown')"
    )
    op.create_check_constraint(
        "ck_documents_parser_backend",
        "documents",
        "parser_backend IS NULL OR parser_backend IN ('mineru', 'pymupdf')",
        schema="scholens",
    )
