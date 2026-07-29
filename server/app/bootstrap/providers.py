"""Explicit infrastructure selection for replaceable application ports."""

from __future__ import annotations

from typing import Literal

from app.modules.papers.application.search import PaperSearchPort
from app.modules.papers.infrastructure.knowledge_search import PostgresPaperSearch
from sqlalchemy.orm import Session


def build_paper_search(
    *,
    backend: Literal["postgres_fts"],
    db: Session,
) -> PaperSearchPort:
    if backend == "postgres_fts":
        return PostgresPaperSearch(db)
    raise ValueError(f"Unsupported paper search backend: {backend}")
