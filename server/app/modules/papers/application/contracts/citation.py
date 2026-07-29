from typing import Any, Literal

from pydantic import BaseModel, Field

CitationMethod = Literal[
    "cached",  # all required fields already present
    "deterministic",  # filled via CrossRef/OpenAlex hydration
    "agentic",  # filled via web search/fetch
    "partial",  # attempted but some required fields still missing
    "not_found",  # paper not found / inaccessible
]

StepKind = Literal[
    "check",
    "deterministic",
    "thinking",
    "web_search",
    "web_fetch",
    "submit",
    "write_back",
    "resolve",
]


class CitationStep(BaseModel):
    """A single step in the citation-finding trajectory, for a user-facing trace."""

    kind: StepKind
    detail: str
    data: dict[str, Any] | None = None


class CitationData(BaseModel):
    """Structured, populated citation metadata. The client renders this into a
    citation string in the user's chosen style — the server does not format it."""

    document_id: str
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    publish_date: str | None = None
    journal: str | None = None
    publisher: str | None = None
    doi: str | None = None


class CitationResult(BaseModel):
    document_id: str
    preferred_style: str  # canonical key (e.g. "APA")
    style_display: str  # human-readable (e.g. "APA 7th Edition")
    data: CitationData
    method: CitationMethod
    missing_fields: list[str] = Field(default_factory=list)
    filled_fields: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None
    steps: list[CitationStep] = Field(default_factory=list)
