"""Short-transaction citation resolution workflow."""

from __future__ import annotations

import logging
from uuid import UUID

from app.bootstrap.adapters.citation_provider import CitationMetadataProvider
from app.bootstrap.capabilities import ApplicationCapabilities
from app.modules.papers.application.citations import (
    CitationMetadataPatch,
    build_citation_result,
)
from app.modules.papers.application.contracts.citation import (
    CitationData,
    CitationResult,
    CitationStep,
)
from app.modules.papers.domain.citations import (
    STYLE_DISPLAY_NAMES,
    CitationFields,
    missing_required_fields,
    normalize_style,
)
from app.modules.papers.application.contracts.search import PaperCollection
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)

logger = logging.getLogger(__name__)


class CitationWorkflow:
    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        provider: CitationMetadataProvider,
        operation_factory: OperationContextFactory,
    ) -> None:
        self._executor = executor
        self._provider = provider
        self._operation_factory = operation_factory

    def run(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        style: str = "APA",
        project_id: UUID | None = None,
        paper_collection: PaperCollection | None = None,
        anchor_document_id: UUID | None = None,
    ) -> CitationResult:
        if paper_collection is not None:
            self._executor.query(
                lambda capabilities: capabilities.paper_collection_access(
                    actor=actor,
                    collection=paper_collection,
                    document_id=document_id,
                    anchor_document_id=anchor_document_id,
                )
            )
        canonical = normalize_style(style)
        display = STYLE_DISPLAY_NAMES[canonical]
        steps: list[CitationStep] = []
        fields = self._read(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        if fields is None:
            return CitationResult(
                document_id=str(document_id),
                preferred_style=canonical,
                style_display=display,
                data=CitationData(document_id=str(document_id)),
                method="not_found",
                steps=[
                    CitationStep(
                        kind="check",
                        detail="Paper not found or access denied.",
                    )
                ],
            )

        missing = missing_required_fields(fields, canonical)
        steps.append(
            CitationStep(
                kind="check",
                detail=f"Fields needed for {display}: {missing or 'none missing'}.",
                data={"missing": missing},
            )
        )
        if not missing:
            return build_citation_result(
                document_id=document_id,
                canonical_style=canonical,
                style_display=display,
                fields=fields,
                method="cached",
                missing_fields=[],
                filled_fields={},
                confidence=None,
                steps=steps,
            )

        try:
            deterministic = self._provider.deterministic(fields=fields)
        except Exception:
            logger.exception(
                "Deterministic citation metadata lookup failed",
                extra={"document_id": str(document_id)},
            )
            deterministic = None
        if deterministic is not None and deterministic.filled_fields:
            fields = self._apply(
                actor=actor,
                parent_operation=operation,
                document_id=document_id,
                project_id=project_id,
                patch=deterministic.patch,
            )
        missing = missing_required_fields(fields, canonical)
        steps.append(
            CitationStep(
                kind="deterministic",
                detail=(
                    "After deterministic metadata lookup, still missing: "
                    f"{missing or 'none'}."
                ),
                data={
                    "missing": missing,
                    "doi": fields.doi,
                    "journal": fields.journal,
                    "publisher": fields.publisher,
                },
            )
        )
        if not missing:
            return build_citation_result(
                document_id=document_id,
                canonical_style=canonical,
                style_display=display,
                fields=fields,
                method="deterministic",
                missing_fields=[],
                filled_fields={},
                confidence=None,
                steps=steps,
            )

        recovered = self._provider.agentic(
            fields=fields,
            missing_fields=missing,
            steps=steps,
        )
        filled_fields: dict[str, object] = {}
        if recovered.filled_fields:
            previous = fields
            fields = self._apply(
                actor=actor,
                parent_operation=operation,
                document_id=document_id,
                project_id=project_id,
                patch=recovered.patch,
            )
            filled_fields = {
                field_name: getattr(fields, field_name)
                for field_name in recovered.filled_fields
                if getattr(previous, field_name) is None
                and getattr(fields, field_name) is not None
            }
            steps.append(
                CitationStep(
                    kind="write_back",
                    detail=(
                        f"Wrote back {list(filled_fields)} "
                        f"(confidence {recovered.confidence})."
                    ),
                    data=filled_fields,
                )
            )
        missing = missing_required_fields(fields, canonical)
        return build_citation_result(
            document_id=document_id,
            canonical_style=canonical,
            style_display=display,
            fields=fields,
            method="agentic" if filled_fields else "partial",
            missing_fields=missing,
            filled_fields=filled_fields,
            confidence=recovered.confidence,
            steps=steps,
        )

    def _read(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> CitationFields | None:
        return self._executor.query(
            lambda capabilities: capabilities.citations.read(
                actor=actor,
                document_id=document_id,
                project_id=project_id,
            )
        )

    def _apply(
        self,
        *,
        actor: Actor,
        parent_operation: OperationContext,
        document_id: UUID,
        project_id: UUID | None,
        patch: CitationMetadataPatch,
    ) -> CitationFields:
        apply_operation = self._operation_factory.child(
            parent_operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        return self._executor.command(
            lambda capabilities: capabilities.citations.apply_missing(
                actor=actor,
                operation=apply_operation,
                document_id=document_id,
                project_id=project_id,
                patch=patch,
            )
        )


__all__ = ["CitationWorkflow"]
