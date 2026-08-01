"""
Backfill document_passages table from existing papers.

Usage:
    python -m app.scripts.backfill_document_passages [--batch-size 100] [--dry-run]
"""

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from app.database.database import SessionLocal
from app.modules.papers.infrastructure.search_repository import (
    document_search_repository,
)
from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def backfill(batch_size: int = 100, dry_run: bool = False) -> None:
    db = SessionLocal()
    try:
        # Count papers that still need indexing (skip already-indexed ones)
        total = int(
            db.execute(
                text(
                    """
                    SELECT COUNT(*) FROM scholens.documents p
                    WHERE p.raw_content IS NOT NULL
                      AND NOT EXISTS (
                        SELECT 1 FROM scholens.document_passages pp
                        WHERE pp.document_id = p.id
                      )
                    """
                )
            ).scalar()
            or 0
        )
        logger.info("passage_backfill.discovery.completed", extra={"paper_count": total})

        indexed = 0
        skipped = 0
        errors = 0
        start_time = time.time()

        # Disable the tsvector trigger during bulk insert — computing
        # to_tsvector per row is the main bottleneck. We'll backfill
        # ts_vector in one UPDATE pass at the end.
        logger.info("paper_search.tsvector_trigger.disabling")
        db.execute(
            text(
                "ALTER TABLE scholens.document_passages "
                "DISABLE TRIGGER document_passages_tsvectorupdate"
            )
        )
        db.commit()

        if not total:
            logger.info("paper_search.passages.no_papers")

        while total > 0:
            # Always OFFSET 0 because each committed batch removes papers
            # from the NOT EXISTS filter.
            rows = db.execute(
                text(
                    """
                    SELECT p.id, p.raw_content
                    FROM scholens.documents p
                    WHERE p.raw_content IS NOT NULL
                      AND NOT EXISTS (
                        SELECT 1 FROM scholens.document_passages pp
                        WHERE pp.document_id = p.id
                      )
                    ORDER BY p.id
                    LIMIT :limit
                """
                ),
                {"limit": batch_size},
            ).fetchall()

            if not rows:
                break

            batch_start = time.time()

            if dry_run:
                for document_id, raw_content in rows:
                    passages = document_search_repository.build_passages(raw_content)
                    logger.info(
                        "passage_backfill.document.dry_run",
                        extra={
                            "document_id": str(document_id),
                            "passage_count": len(passages),
                        },
                    )
                    skipped += 1
            else:
                # Build all passages for the batch in memory, then bulk insert.
                # No DELETE needed — the NOT EXISTS filter guarantees these
                # papers have no existing passages.
                all_passages = []
                for document_id, raw_content in rows:
                    try:
                        for p in document_search_repository.build_passages(raw_content):
                            all_passages.append({"document_id": document_id, **p})
                    except Exception:
                        errors += 1
                        logger.exception(
                            "passage_backfill.document.failed",
                            extra={"document_id": str(document_id)},
                        )

                if all_passages:
                    db.execute(
                        text(
                            """
                            INSERT INTO scholens.document_passages
                                (document_id, start_line, end_line, content)
                            VALUES (:document_id, :start_line, :end_line, :content)
                            ON CONFLICT (document_id, start_line) DO NOTHING
                        """
                        ),
                        all_passages,
                    )
                    db.commit()

                indexed += len(rows) - errors

            elapsed = time.time() - start_time
            batch_elapsed = time.time() - batch_start
            rate = indexed / elapsed if elapsed > 0 else 0
            remaining = (total - indexed) / rate if rate > 0 else 0
            logger.info(
                "passage_backfill.progress",
                extra={
                    "indexed": indexed,
                    "total": total,
                    "percent": indexed * 100 // total,
                    "batch_seconds": round(batch_elapsed, 3),
                    "papers_per_second": round(rate, 3),
                    "error_count": errors,
                    "eta_minutes": round(remaining / 60, 3),
                },
            )

        # Backfill ts_vector in batches (no upfront COUNT to avoid full table scan)
        ts_batch_size = 100_000
        logger.info(
            "passage_backfill.search_vector.started",
            extra={"batch_size": ts_batch_size},
        )
        ts_start = time.time()
        ts_updated = 0

        while True:
            result = db.execute(
                text(
                    """
                    UPDATE scholens.document_passages
                    SET ts_vector = to_tsvector('pg_catalog.english', coalesce(content, ''))
                    WHERE id IN (
                        SELECT id FROM scholens.document_passages
                        WHERE ts_vector IS NULL
                        LIMIT :batch_size
                    )
                """
                ),
                {"batch_size": ts_batch_size},
            )
            db.commit()
            updated = int(getattr(result, "rowcount", 0) or 0)
            if updated == 0:
                break
            ts_updated += updated
            elapsed = time.time() - ts_start
            rate = ts_updated / elapsed if elapsed > 0 else 0
            logger.info(
                "passage_backfill.search_vector.progress",
                extra={
                    "updated_rows": ts_updated,
                    "rows_per_second": round(rate, 3),
                    "elapsed_minutes": round(elapsed / 60, 3),
                },
            )

        logger.info(
            "passage_backfill.search_vector.completed",
            extra={
                "updated_rows": ts_updated,
                "elapsed_minutes": round((time.time() - ts_start) / 60, 3),
            },
        )

        # Re-enable the trigger for future inserts
        logger.info("paper_search.tsvector_trigger.enabling")
        db.execute(
            text(
                "ALTER TABLE scholens.document_passages "
                "ENABLE TRIGGER document_passages_tsvectorupdate"
            )
        )
        db.commit()

        elapsed = time.time() - start_time
        logger.info(
            "passage_backfill.completed",
            extra={
                "elapsed_minutes": round(elapsed / 60, 3),
                "indexed": indexed,
                "error_count": errors,
                "skipped": skipped,
            },
        )
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill document_passages table")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    backfill(batch_size=args.batch_size, dry_run=args.dry_run)
