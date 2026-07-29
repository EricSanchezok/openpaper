"""Citation resolution use case shared by HTTP, Agent, and future MCP."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.modules.papers.application.contracts.citation import (
    CitationData,
    CitationMethod,
    CitationResult,
    CitationStep,
)
from app.modules.papers.domain.citations import (
    STYLE_DISPLAY_NAMES,
    CitationFields,
    missing_required_fields,
    normalize_style,
)
from app.shared.application import Actor


class CitationMetadataGateway(Protocol):
    def read(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> CitationFields | None: ...

    def hydrate(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> CitationFields | None: ...

    def recover(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
        missing_fields: list[str],
        steps: list[CitationStep],
    ) -> tuple[CitationFields | None, dict[str, object], float | None]: ...


class ResolveCitation:
    def __init__(self, gateway: CitationMetadataGateway) -> None:
        self._gateway = gateway

    def __call__(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        style: str = "APA",
        project_id: UUID | None = None,
    ) -> CitationResult:
        canonical = normalize_style(style)
        display = STYLE_DISPLAY_NAMES[canonical]
        steps: list[CitationStep] = []
        fields = self._gateway.read(
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
                detail=(f"Fields needed for {display}: {missing or 'none missing'}."),
                data={"missing": missing},
            )
        )
        if not missing:
            return self._result(
                document_id=document_id,
                canonical=canonical,
                display=display,
                fields=fields,
                method="cached",
                missing=[],
                filled={},
                confidence=None,
                steps=steps,
            )

        hydrated = self._gateway.hydrate(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        if hydrated is not None:
            fields = hydrated
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
            return self._result(
                document_id=document_id,
                canonical=canonical,
                display=display,
                fields=fields,
                method="deterministic",
                missing=[],
                filled={},
                confidence=None,
                steps=steps,
            )

        recovered, filled, confidence = self._gateway.recover(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
            missing_fields=missing,
            steps=steps,
        )
        if recovered is not None:
            fields = recovered
        missing = missing_required_fields(fields, canonical)
        method: CitationMethod = "agentic" if filled else "partial"
        return self._result(
            document_id=document_id,
            canonical=canonical,
            display=display,
            fields=fields,
            method=method,
            missing=missing,
            filled=filled,
            confidence=confidence,
            steps=steps,
        )

    @staticmethod
    def _result(
        *,
        document_id: UUID,
        canonical: str,
        display: str,
        fields: CitationFields,
        method: CitationMethod,
        missing: list[str],
        filled: dict[str, object],
        confidence: float | None,
        steps: list[CitationStep],
    ) -> CitationResult:
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
            missing_fields=missing,
            filled_fields=filled,
            confidence=confidence,
            steps=steps,
        )
