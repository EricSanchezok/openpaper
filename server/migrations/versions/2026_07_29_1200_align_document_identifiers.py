"""align document identifier names

Revision ID: d9079f37cdb1
Revises: a21f80661812
Create Date: 2026-07-29 12:00:00+00:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "d9079f37cdb1"
down_revision: str | None = "a21f80661812"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Name canonical-document references consistently."""
    op.rename_table(
        "paper_passages",
        "document_passages",
        schema="scholens",
    )
    op.alter_column(
        "document_passages",
        "paper_id",
        new_column_name="document_id",
        schema="scholens",
    )
    op.alter_column(
        "zotero_imported_items",
        "paper_id",
        new_column_name="document_id",
        schema="scholens",
    )

    op.execute(
        "ALTER TABLE scholens.document_passages "
        "RENAME CONSTRAINT paper_passages_pkey TO document_passages_pkey"
    )
    op.execute(
        "ALTER TABLE scholens.document_passages "
        "RENAME CONSTRAINT paper_passages_paper_id_fkey "
        "TO document_passages_document_id_fkey"
    )
    op.execute(
        "ALTER TABLE scholens.document_passages "
        "RENAME CONSTRAINT paper_passages_paper_id_start_line_key "
        "TO document_passages_document_id_start_line_key"
    )
    op.execute(
        "ALTER INDEX scholens.ix_scholens_paper_passages_paper_id "
        "RENAME TO ix_scholens_document_passages_document_id"
    )
    op.execute(
        "ALTER INDEX scholens.ix_paper_passages_ts_vector "
        "RENAME TO ix_document_passages_ts_vector"
    )
    op.execute(
        "ALTER SEQUENCE scholens.paper_passages_id_seq "
        "RENAME TO document_passages_id_seq"
    )
    op.execute(
        "ALTER TABLE scholens.zotero_imported_items "
        "RENAME CONSTRAINT zotero_imported_items_paper_id_fkey "
        "TO zotero_imported_items_document_id_fkey"
    )
    op.execute(
        "ALTER FUNCTION scholens.paper_passages_tsvector_trigger() "
        "RENAME TO document_passages_tsvector_trigger"
    )
    op.execute(
        "ALTER TRIGGER paper_passages_tsvectorupdate "
        "ON scholens.document_passages "
        "RENAME TO document_passages_tsvectorupdate"
    )


def downgrade() -> None:
    """Restore the former paper-oriented storage names."""
    op.execute(
        "ALTER TRIGGER document_passages_tsvectorupdate "
        "ON scholens.document_passages "
        "RENAME TO paper_passages_tsvectorupdate"
    )
    op.execute(
        "ALTER FUNCTION scholens.document_passages_tsvector_trigger() "
        "RENAME TO paper_passages_tsvector_trigger"
    )
    op.execute(
        "ALTER TABLE scholens.zotero_imported_items "
        "RENAME CONSTRAINT zotero_imported_items_document_id_fkey "
        "TO zotero_imported_items_paper_id_fkey"
    )
    op.execute(
        "ALTER TABLE scholens.document_passages "
        "RENAME CONSTRAINT document_passages_document_id_fkey "
        "TO document_passages_paper_id_fkey"
    )
    op.execute(
        "ALTER SEQUENCE scholens.document_passages_id_seq "
        "RENAME TO paper_passages_id_seq"
    )
    op.execute(
        "ALTER INDEX scholens.ix_document_passages_ts_vector "
        "RENAME TO ix_paper_passages_ts_vector"
    )
    op.execute(
        "ALTER INDEX scholens.ix_scholens_document_passages_document_id "
        "RENAME TO ix_scholens_paper_passages_paper_id"
    )
    op.execute(
        "ALTER TABLE scholens.document_passages "
        "RENAME CONSTRAINT document_passages_document_id_start_line_key "
        "TO paper_passages_paper_id_start_line_key"
    )
    op.execute(
        "ALTER TABLE scholens.document_passages "
        "RENAME CONSTRAINT document_passages_pkey TO paper_passages_pkey"
    )

    op.alter_column(
        "zotero_imported_items",
        "document_id",
        new_column_name="paper_id",
        schema="scholens",
    )
    op.alter_column(
        "document_passages",
        "document_id",
        new_column_name="paper_id",
        schema="scholens",
    )
    op.rename_table(
        "document_passages",
        "paper_passages",
        schema="scholens",
    )
