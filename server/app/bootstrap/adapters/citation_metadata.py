"""Cross-module persistence and provider adapter for citation resolution."""

from __future__ import annotations

import logging
from uuid import UUID

from app.helpers.metadata_hydration import hydrate_paper_metadata
from app.llm.citation_recovery import MetadataRecoveryAgent
from app.database.models import Document
from app.modules.papers.application.contracts.citation import CitationStep
from app.modules.papers.domain.citations import CitationFields, fields_from_paper
from app.modules.papers.infrastructure.repository import document_repository
from app.bootstrap.adapters.project_documents import (
    project_document_repository,
)
from app.shared.application import Actor
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class DefaultCitationMetadataGateway:
    def __init__(
        self,
        db: Session,
        recovery: MetadataRecoveryAgent | None = None,
    ) -> None:
        self._db = db
        self._recovery = recovery or MetadataRecoveryAgent()

    def _paper(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> Document | None:
        try:
            if project_id is not None:
                return project_document_repository.get_paper_by_project(
                    self._db,
                    document_id=document_id,
                    project_id=project_id,
                    user=actor,
                )
            return document_repository.find_accessible(
                self._db,
                document_id=str(document_id),
                user=actor,
            )
        except Exception:
            logger.exception("Failed to load paper %s for citation", document_id)
            return None

    def read(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> CitationFields | None:
        paper = self._paper(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        return fields_from_paper(paper) if paper is not None else None

    def hydrate(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> CitationFields | None:
        paper = self._paper(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        if paper is None:
            return None
        hydrated = hydrate_paper_metadata(
            db=self._db,
            paper=paper,
            user=actor,
            force=True,
        )
        return fields_from_paper(hydrated)

    def recover(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
        missing_fields: list[str],
        steps: list[CitationStep],
    ) -> tuple[CitationFields | None, dict[str, object], float | None]:
        paper = self._paper(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        if paper is None:
            return None, {}, None
        recovered, filled, confidence = self._recovery.recover_metadata(
            db=self._db,
            paper=paper,
            user=actor,
            missing_hint=missing_fields,
            steps=steps,
        )
        return fields_from_paper(recovered), dict(filled), confidence
