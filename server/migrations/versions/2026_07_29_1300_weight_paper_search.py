"""weight all searchable document metadata

Revision ID: f6c2b752174e
Revises: d9079f37cdb1
Create Date: 2026-07-29 13:00:00+00:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "f6c2b752174e"
down_revision: str | None = "d9079f37cdb1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Index metadata and body behind the stable PostgreSQL search adapter."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION scholens.document_content_trigger()
        RETURNS trigger AS $$
        BEGIN
            NEW.ts_vector :=
                setweight(
                    to_tsvector('pg_catalog.english', coalesce(NEW.title, '')),
                    'A'
                ) ||
                setweight(
                    to_tsvector(
                        'pg_catalog.english',
                        coalesce(array_to_string(NEW.authors, ' '), '')
                    ),
                    'A'
                ) ||
                setweight(
                    to_tsvector(
                        'pg_catalog.english',
                        coalesce(array_to_string(NEW.keywords, ' '), '')
                    ),
                    'B'
                ) ||
                setweight(
                    to_tsvector('pg_catalog.english', coalesce(NEW.abstract, '')),
                    'C'
                ) ||
                setweight(
                    to_tsvector('pg_catalog.english', coalesce(NEW.raw_content, '')),
                    'D'
                );
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("UPDATE scholens.documents SET title = title")


def downgrade() -> None:
    """Restore the original title-and-body search vector."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION scholens.document_content_trigger()
        RETURNS trigger AS $$
        BEGIN
            NEW.ts_vector :=
                setweight(
                    to_tsvector('pg_catalog.english', coalesce(NEW.title, '')),
                    'A'
                ) ||
                setweight(
                    to_tsvector('pg_catalog.english', coalesce(NEW.raw_content, '')),
                    'D'
                );
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("UPDATE scholens.documents SET title = title")
