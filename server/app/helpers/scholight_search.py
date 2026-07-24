"""Scholight MCP integration for Scholens's Discover result cards."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.integrations.mcp import SCHOLIGHT_MCP


@dataclass(slots=True)
class ScholightResult:
    title: str
    url: str
    authors: list[str] = field(default_factory=list)
    published_date: Optional[str] = None
    text: Optional[str] = None
    highlights: list[str] = field(default_factory=list)
    highlight_scores: list[float] = field(default_factory=list)
    favicon: Optional[str] = None
    summary: Optional[str] = None
    source: str = "Scholight"

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "authors": self.authors,
            "published_date": self.published_date,
            "text": self.text,
            "highlights": self.highlights,
            "highlight_scores": self.highlight_scores,
            "favicon": self.favicon,
            "summary": self.summary,
            "source": self.source,
        }


async def search_scholight(
    query: str,
    *,
    num_results: int = 10,
    date_from: str | None = None,
) -> list[ScholightResult]:
    """Call Scholight's existing `search_papers` MCP tool."""
    arguments: dict[str, Any] = {
        "query": query,
        "strength": "standard",
        "limit": max(1, min(num_results, 20)),
    }
    if date_from is not None:
        arguments["date_from"] = date_from

    response = await SCHOLIGHT_MCP.call_tool("search_papers", arguments)
    if not isinstance(response, dict) or not isinstance(response.get("hits"), list):
        raise RuntimeError("Scholight MCP returned an invalid search response")

    results: list[ScholightResult] = []
    for hit in response["hits"]:
        if not isinstance(hit, dict):
            continue
        title = hit.get("title")
        url = hit.get("arxiv_url")
        if not isinstance(title, str) or not isinstance(url, str):
            continue
        abstract = hit.get("abstract")
        results.append(
            ScholightResult(
                title=title,
                url=url,
                authors=[
                    author
                    for author in hit.get("authors", [])
                    if isinstance(author, str)
                ],
                published_date=(
                    hit.get("submitted_at")
                    if isinstance(hit.get("submitted_at"), str)
                    else None
                ),
                text=abstract if isinstance(abstract, str) else None,
                summary=abstract if isinstance(abstract, str) else None,
            )
        )
    return results
