"""SQLAlchemy persistence adapter for citation metadata."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.adapters.project_documents import project_document_repository
from app.database.models import Document
from app.modules.papers.application.citations import (
    CitationMetadataPatch,
    CitationMetadataWrite,
)
from app.modules.papers.application.contracts.documents import DocumentUpdate
from app.modules.papers.domain.citations import CitationFields, fields_from_paper
from app.modules.papers.infrastructure.repository import document_repository
from app.shared.application import Actor
from sqlalchemy.orm import Session


class SqlAlchemyCitationMetadataStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _paper(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> Document | None:
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

    def apply_missing(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
        patch: CitationMetadataPatch,
    ) -> CitationMetadataWrite:
        paper = self._paper(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        if paper is None:
            return CitationMetadataWrite(CitationFields(), changed=False)

        candidates = {
            "doi": patch.doi,
            "journal": patch.journal,
            "publisher": patch.publisher,
            "publish_date": patch.publish_date,
        }
        changes: dict[str, object] = {
            field_name: value
            for field_name, value in candidates.items()
            if value is not None and getattr(paper, field_name) is None
        }
        if patch.field_provenance is not None and changes:
            provenance = dict(paper.field_provenance or {})
            provenance.update(
                {
                    field_name: patch.field_provenance[field_name]
                    for field_name in changes
                    if field_name in patch.field_provenance
                }
            )
            changes["field_provenance"] = provenance
        if not changes:
            return CitationMetadataWrite(fields_from_paper(paper), changed=False)

        updated = document_repository.update_canonical(
            self._db,
            document=paper,
            update=DocumentUpdate.model_validate(changes),
            user=actor,
        )
        return CitationMetadataWrite(
            fields=fields_from_paper(updated or paper),
            changed=updated is not None,
        )


__all__ = ["SqlAlchemyCitationMetadataStore"]
