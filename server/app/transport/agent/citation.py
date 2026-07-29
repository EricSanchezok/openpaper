"""Agent adapter for the shared paper citation application capability."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.modules.papers.application.contracts.citation import CitationResult
from app.shared.application import Actor, ApplicationExecutor

find_citation_function = {
    "name": "find_citation",
    "description": (
        "Produce a bibliographic citation for one specific paper. Use this "
        "when the user asks for a citation, reference, or bibliography entry. "
        "Missing publication metadata is resolved automatically."
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
                    "APA, MLA, IEEE, Chicago, Harvard, AMA, AAA, or BibTeX."
                ),
            },
        },
        "required": ["document_id"],
    },
}


def run_find_citation(
    document_id: str,
    current_user: Actor,
    executor: ApplicationExecutor[ApplicationCapabilities],
    style: str = "APA",
    project_id: str | None = None,
    restrict_to_document_ids: list[str] | None = None,
) -> CitationResult:
    """Match the evidence loop's tool-call signature."""
    if (
        restrict_to_document_ids is not None
        and document_id not in restrict_to_document_ids
    ):
        raise ValueError("Paper is not in the scoped set for this conversation")
    return executor.query(
        lambda capabilities: capabilities.citations(
            actor=current_user,
            document_id=UUID(document_id),
            style=style,
            project_id=UUID(project_id) if project_id else None,
        )
    )
