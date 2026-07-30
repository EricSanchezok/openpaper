"""Citation metadata persistence and transport-neutral result construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.modules.papers.application.contracts.citation import (
    CitationData,
    CitationMethod,
    CitationResult,
    CitationStep,
)
from app.modules.papers.domain.citations import CitationFields
from app.shared.application import Actor, OperationContext
from app.shared.domain import JsonValue

PAPER_CITATION_METADATA_UPDATED = OperationAction("paper.citation_metadata_updated")


@dataclass(frozen=True, slots=True)
class CitationMetadataPatch:
    doi: str | None = None
    journal: str | None = None
    publisher: str | None = None
    publish_date: str | None = None
    field_provenance: dict[str, JsonValue] | None = None


@dataclass(frozen=True, slots=True)
class CitationMetadataWrite:
    fields: CitationFields
    changed: bool


class CitationMetadataStore(Protocol):
    def read(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> CitationFields | None: ...

    def apply_missing(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
        patch: CitationMetadataPatch,
    ) -> CitationMetadataWrite: ...


class CitationMetadata:
    """Read citation facts and atomically apply provider findings."""

    def __init__(
        self,
        store: CitationMetadataStore,
        *,
        journal: OperationJournal,
    ) -> None:
        self._store = store
        self._journal = journal

    def read(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> CitationFields | None:
        return self._store.read(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )

    def apply_missing(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        project_id: UUID | None,
        patch: CitationMetadataPatch,
    ) -> CitationFields:
        result = self._store.apply_missing(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
            patch=patch,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=PAPER_CITATION_METADATA_UPDATED,
                resources=(ResourceRef("document", str(document_id)),),
            )
        return result.fields


def build_citation_result(
    *,
    document_id: UUID,
    canonical_style: str,
    style_display: str,
    fields: CitationFields,
    method: CitationMethod,
    missing_fields: list[str],
    filled_fields: dict[str, object],
    confidence: float | None,
    steps: list[CitationStep],
) -> CitationResult:
    steps.append(
        CitationStep(
            kind="resolve",
            detail=f"Resolved citation metadata; preferred style {style_display}.",
            data={"missing": missing_fields},
        )
    )
    return CitationResult(
        document_id=str(document_id),
        preferred_style=canonical_style,
        style_display=style_display,
        data=CitationData(
            document_id=str(document_id),
            title=fields.title,
            authors=fields.authors,
            publish_date=fields.publish_date,
            journal=fields.journal,
            publisher=fields.publisher,
            doi=fields.doi,
        ),
        method=method,
        missing_fields=missing_fields,
        filled_fields=filled_fields,
        confidence=confidence,
        steps=steps,
    )


__all__ = [
    "CitationMetadata",
    "CitationMetadataPatch",
    "CitationMetadataStore",
    "CitationMetadataWrite",
    "build_citation_result",
]
