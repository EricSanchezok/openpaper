"""Agent adapter for the shared paper citation application capability."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.modules.papers.application.contracts.citation import CitationResult
from app.shared.application import Actor, ApplicationExecutor
from app.modules.conversations.application.chat import ConversationChatScope
from app.transport.agent.paper_tools import _ensure_paper_in_scope

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
    conversation_scope: ConversationChatScope,
    style: str = "APA",
) -> CitationResult:
    """Match the evidence loop's tool-call signature."""
    _ensure_paper_in_scope(document_id, current_user, executor, conversation_scope)
    return executor.query(
        lambda capabilities: capabilities.citations(
            actor=current_user,
            document_id=UUID(document_id),
            style=style,
        )
    )
