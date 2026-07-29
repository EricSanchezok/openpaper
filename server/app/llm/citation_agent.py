"""find_citation: render a paper's citation in a requested style, recovering
missing bibliographic metadata when needed.

Strategy (cheapest first):
  1. cached        — all required fields present, render immediately.
  2. deterministic — fill via the shared CrossRef/OpenAlex hydration seam.
  3. agentic       — delegate to `MetadataRecoveryAgent` (MCP search + extraction
                     + confidence-gated null-only write-back with provenance).

This module is the chat-tool-facing layer. The agentic loop itself lives in
`app.llm.citation_recovery` so `app.helpers.metadata_hydration` can call it
without an import cycle.
"""

import logging
import uuid
from typing import Any

from app.repositories.documents import document_repository
from app.repositories.project_documents import project_document_repository
from app.database.models import Document
from app.helpers.citations import (
    STYLE_DISPLAY_NAMES,
    CitationFields,
    fields_from_paper,
    missing_required_fields,
    normalize_style,
)
from app.helpers.metadata_hydration import hydrate_paper_metadata
from app.llm.citation_recovery import MetadataRecoveryAgent
from app.schemas.citation import (
    CitationData,
    CitationMethod,
    CitationResult,
    CitationStep,
)
from app.shared.application import Actor
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


find_citation_function = {
    "name": "find_citation",
    "description": (
        "Produce a bibliographic citation for ONE specific paper. Use this "
        "whenever the user asks for a citation, reference, or bibliography "
        "entry (in APA, MLA, IEEE, Chicago, Harvard, AMA, AAA, or BibTeX). It "
        "resolves any missing publication metadata (journal/venue, publisher, "
        "DOI, date) automatically, and the resulting citation is presented to "
        "the user for you. Call it once per paper the user wants cited."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "document_id": {
                "type": "string",
                "description": "The ID of the paper to cite.",
            },
            "style": {
                "type": "string",
                "description": (
                    "Preferred citation style requested by the user, e.g. "
                    "'APA 7th edition', 'MLA', 'IEEE', 'Chicago', 'Harvard', "
                    "'AMA', 'AAA', 'BibTeX'. Defaults to APA if unspecified."
                ),
            },
        },
        "required": ["document_id"],
    },
}


class CitationFinder(MetadataRecoveryAgent):
    """Chat-surface agent: cached -> deterministic -> agentic citation finding."""

    def find_citation(
        self,
        *,
        db: Session,
        document_id: str,
        style: str,
        current_user: Actor,
        project_id: str | None = None,
    ) -> CitationResult:
        canonical = normalize_style(style)
        display = STYLE_DISPLAY_NAMES[canonical]
        steps: list[CitationStep] = []

        paper = self._load_paper(db, document_id, current_user, project_id)
        if not paper:
            return CitationResult(
                document_id=document_id,
                preferred_style=canonical,
                style_display=display,
                data=CitationData(document_id=document_id),
                method="not_found",
                steps=[
                    CitationStep(
                        kind="check", detail="Paper not found or access denied."
                    )
                ],
            )

        # 1. Cached: all required fields already present.
        fields = fields_from_paper(paper)
        missing = missing_required_fields(fields, canonical)
        steps.append(
            CitationStep(
                kind="check",
                detail=f"Fields needed for {display}: {missing or 'none missing'}.",
                data={"missing": missing},
            )
        )
        if not missing:
            return self._finalize(
                document_id, canonical, display, fields, "cached", [], {}, None, steps
            )

        # 2. Deterministic hydration via the shared seam (CrossRef/OpenAlex).
        paper = hydrate_paper_metadata(
            db=db, paper=paper, user=current_user, force=True
        )
        fields = fields_from_paper(paper)
        missing = missing_required_fields(fields, canonical)
        steps.append(
            CitationStep(
                kind="deterministic",
                detail=f"After CrossRef/OpenAlex lookup, still missing: {missing or 'none'}.",
                data={
                    "missing": missing,
                    "doi": fields.doi,
                    "journal": fields.journal,
                    "publisher": fields.publisher,
                },
            )
        )
        if not missing:
            return self._finalize(
                document_id,
                canonical,
                display,
                fields,
                "deterministic",
                [],
                {},
                None,
                steps,
            )

        # 3. Agentic web recovery for whatever the style still needs.
        paper, filled, confidence = self.recover_metadata(
            db=db,
            paper=paper,
            user=current_user,
            missing_hint=missing,
            steps=steps,
        )
        fields = fields_from_paper(paper)
        missing = missing_required_fields(fields, canonical)
        method: CitationMethod = "agentic" if filled else "partial"
        return self._finalize(
            document_id,
            canonical,
            display,
            fields,
            method,
            missing,
            filled,
            confidence,
            steps,
        )

    def _load_paper(
        self,
        db: Session,
        document_id: str,
        current_user: Actor,
        project_id: str | None,
    ) -> Document | None:
        try:
            if project_id:
                return project_document_repository.get_paper_by_project(
                    db,
                    document_id=uuid.UUID(document_id),
                    project_id=uuid.UUID(project_id),
                    user=current_user,
                )
            return document_repository.find_accessible(
                db, document_id=document_id, user=current_user
            )
        except Exception:
            logger.exception("Failed to load paper %s for citation", document_id)
            return None

    def _finalize(
        self,
        document_id: str,
        canonical: str,
        display: str,
        fields: CitationFields,
        method: CitationMethod,
        missing: list[str],
        filled: dict[str, Any],
        confidence: float | None,
        steps: list[CitationStep],
    ) -> CitationResult:
        data = CitationData(
            document_id=str(document_id),
            title=fields.title,
            authors=fields.authors,
            publish_date=fields.publish_date,
            journal=fields.journal,
            publisher=fields.publisher,
            doi=fields.doi,
        )
        steps.append(
            CitationStep(
                kind="resolve",
                detail=f"Resolved citation metadata; preferred style {display}.",
                data={"missing": missing},
            )
        )
        return CitationResult(
            document_id=str(document_id),
            preferred_style=canonical,
            style_display=display,
            data=data,
            method=method,
            missing_fields=missing,
            filled_fields=filled,
            confidence=confidence,
            steps=steps,
        )


_finder: CitationFinder | None = None


def _get_finder() -> CitationFinder:
    global _finder
    if _finder is None:
        _finder = CitationFinder()
    return _finder


def run_find_citation(
    document_id: str,
    current_user: Actor,
    db: Session,
    style: str = "APA",
    project_id: str | None = None,
    restrict_to_document_ids: list[str] | None = None,
) -> CitationResult:
    """Tool entry point matching the multi-paper evidence loop's call signature."""
    if (
        restrict_to_document_ids is not None
        and document_id not in restrict_to_document_ids
    ):
        raise ValueError("Paper is not in the scoped set for this conversation")
    return _get_finder().find_citation(
        db=db,
        document_id=document_id,
        style=style,
        current_user=current_user,
        project_id=project_id,
    )
