"""AnySearch MCP adapter for Discover result cards."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.integrations.mcp import ANYSEARCH_MCP


@dataclass(slots=True)
class AnySearchResult:
    title: str
    url: str
    text: str | None = None
    source: str = "AnySearch"

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "text": self.text,
            "summary": self.text,
            "source": self.source,
            "authors": [],
            "highlights": [],
            "highlight_scores": [],
        }


def _result_from_mapping(item: dict[str, Any]) -> AnySearchResult | None:
    title = item.get("title") or item.get("name")
    url = item.get("url") or item.get("link")
    if not isinstance(title, str) or not isinstance(url, str):
        return None
    snippet = item.get("snippet") or item.get("text") or item.get("content")
    return AnySearchResult(
        title=title,
        url=url,
        text=snippet if isinstance(snippet, str) else None,
    )


def _parse_markdown_results(value: str) -> list[AnySearchResult]:
    blocks = re.split(r"(?m)^### \d+\. ", value)
    results: list[AnySearchResult] = []
    for block in blocks[1:]:
        lines = block.strip().splitlines()
        if not lines:
            continue
        url_match = re.search(r"(?m)^- \*\*URL\*\*: (https?://\S+)", block)
        if not url_match:
            continue
        snippet_lines = [
            line
            for line in lines[1:]
            if not line.startswith("- **URL**:") and not line.startswith("- **")
        ]
        results.append(
            AnySearchResult(
                title=lines[0].strip(),
                url=url_match.group(1),
                text="\n".join(snippet_lines).strip() or None,
            )
        )
    return results


async def search_anysearch(
    query: str,
    *,
    num_results: int = 10,
    domains: list[str] | None = None,
) -> list[AnySearchResult]:
    scoped_query = query
    if domains:
        sites = " OR ".join(f"site:{domain}" for domain in domains)
        scoped_query = f"{query} ({sites})"
    response = await ANYSEARCH_MCP.call_tool(
        "search",
        {"query": scoped_query, "max_results": max(1, min(num_results, 10))},
    )

    if isinstance(response, str):
        return _parse_markdown_results(response)
    if isinstance(response, dict):
        raw_results = response.get("results", [])
    elif isinstance(response, list):
        raw_results = response
    else:
        raise RuntimeError("AnySearch MCP returned an invalid search response")

    return [
        result
        for item in raw_results
        if isinstance(item, dict) and (result := _result_from_mapping(item)) is not None
    ]
