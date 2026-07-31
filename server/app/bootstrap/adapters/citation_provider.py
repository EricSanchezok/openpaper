"""External citation metadata providers with no persistence responsibility."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.helpers.paper_search import extract_doi_from_url, get_doi, get_enriched_data
from app.helpers.parser import parse_publication_date
from app.llm.citation_recovery import MetadataRecoveryAgent
from app.modules.integrations.connectors.infrastructure.mcp import ConnectorToolResolver
from app.modules.papers.application.citations import CitationMetadataPatch
from app.modules.papers.application.contracts.citation import CitationStep
from app.modules.papers.domain.citations import CitationFields
from app.shared.application import Actor
from app.shared.domain import JsonValue


@dataclass(frozen=True, slots=True)
class CitationProviderResult:
    patch: CitationMetadataPatch
    filled_fields: dict[str, object]
    confidence: float | None = None


class CitationMetadataProvider:
    def __init__(self, connector_tools: ConnectorToolResolver) -> None:
        self._recovery = MetadataRecoveryAgent(connector_tools)

    def deterministic(
        self,
        *,
        fields: CitationFields,
    ) -> CitationProviderResult:
        doi = fields.doi
        if not doi and fields.title:
            doi = get_doi(fields.title, fields.authors or None)

        journal = fields.journal
        publisher = fields.publisher
        publish_date = fields.publish_date
        if doi and (not journal or not publisher):
            enriched = get_enriched_data(doi)
            if enriched is not None:
                journal = journal or enriched.journal
                publisher = publisher or enriched.publisher
                if not publish_date and enriched.publication_date:
                    parsed = parse_publication_date(enriched.publication_date)
                    publish_date = parsed.isoformat() if parsed is not None else None

        filled: dict[str, object] = {
            field_name: value
            for field_name, value in {
                "doi": doi if not fields.doi else None,
                "journal": journal if not fields.journal else None,
                "publisher": publisher if not fields.publisher else None,
                "publish_date": publish_date if not fields.publish_date else None,
            }.items()
            if value is not None
        }
        return CitationProviderResult(
            patch=CitationMetadataPatch(
                doi=str(filled["doi"]) if "doi" in filled else None,
                journal=(str(filled["journal"]) if "journal" in filled else None),
                publisher=(str(filled["publisher"]) if "publisher" in filled else None),
                publish_date=(
                    str(filled["publish_date"]) if "publish_date" in filled else None
                ),
            ),
            filled_fields=filled,
        )

    def agentic(
        self,
        *,
        actor: Actor,
        fields: CitationFields,
        missing_fields: list[str],
        steps: list[CitationStep],
        filled_by: str = "get_paper_citation",
    ) -> CitationProviderResult:
        findings, confidence = self._recovery.find_metadata(
            actor=actor,
            fields=fields,
            missing_fields=missing_fields,
            steps=steps,
        )
        if not findings:
            return CitationProviderResult(
                patch=CitationMetadataPatch(),
                filled_fields={},
                confidence=confidence,
            )

        doi_value = findings.get("doi")
        doi = (
            extract_doi_from_url(str(doi_value)) or str(doi_value)
            if doi_value
            else None
        )
        publish_date_value = findings.get("publish_date")
        parsed_date = (
            parse_publication_date(str(publish_date_value))
            if publish_date_value
            else None
        )
        values = {
            "journal": _optional_string(findings.get("journal")),
            "publisher": _optional_string(findings.get("publisher")),
            "doi": doi,
            "publish_date": parsed_date.isoformat() if parsed_date else None,
        }
        filled: dict[str, object] = {
            field_name: value
            for field_name, value in values.items()
            if value is not None and getattr(fields, field_name) is None
        }
        now = datetime.now(timezone.utc).isoformat()
        source_url = _optional_string(findings.get("source_url"))
        provenance: dict[str, JsonValue] = {
            field_name: {
                "source_url": source_url,
                "filled_by": filled_by,
                "confidence": confidence,
                "filled_at": now,
            }
            for field_name in filled
        }
        return CitationProviderResult(
            patch=CitationMetadataPatch(
                doi=str(filled["doi"]) if "doi" in filled else None,
                journal=(str(filled["journal"]) if "journal" in filled else None),
                publisher=(str(filled["publisher"]) if "publisher" in filled else None),
                publish_date=(
                    str(filled["publish_date"]) if "publish_date" in filled else None
                ),
                field_provenance=provenance,
            ),
            filled_fields=filled,
            confidence=confidence,
        )


def _optional_string(value: object) -> str | None:
    return str(value) if value else None


__all__ = ["CitationMetadataProvider", "CitationProviderResult"]
