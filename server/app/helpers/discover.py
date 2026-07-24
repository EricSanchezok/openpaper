"""Discovery pipeline: decompose research questions into subqueries and search."""

import logging
from datetime import datetime, timedelta
from typing import Any, AsyncGenerator, List, Optional

from app.helpers.anysearch_search import search_anysearch
from app.helpers.openalex_search import search_openalex
from app.helpers.scholight_search import search_scholight
from app.llm.base import BaseLLMClient
from app.schemas.discover import DISCOVER_SOURCES
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

llm_client = BaseLLMClient()

DECOMPOSE_PROMPT = """You are a research assistant helping find academic papers. Given a research question, generate 2-5 search subqueries.

Guidelines:
- The FIRST subquery should be a direct, general search closely matching the original question's core intent
- Additional subqueries can explore specific aspects, related concepts, or alternative phrasings
- Vary specificity: include both broad and narrow queries
- If the original question is already specific and well-formed, fewer subqueries (2-3) may be better
- Each subquery should be a concise search phrase suitable for academic paper search
- Avoid over-decomposing simple questions into overly narrow fragments"""


class DecomposeResponse(BaseModel):
    subqueries: List[str] = Field(
        description="A list of 2-5 targeted search subqueries for finding relevant research papers.",
        min_length=2,
        max_length=5,
    )


def decompose_query(question: str) -> list[str]:
    """Use LLM to decompose a research question into targeted subqueries."""
    response = llm_client.generate_content(
        contents=question,
        system_prompt=DECOMPOSE_PROMPT,
        response_model=DecomposeResponse,
    )

    return DecomposeResponse.model_validate_json(response.text).subqueries


async def run_discover_pipeline(
    question: str,
    sources: Optional[list[str]] = None,
    sort: Optional[str] = None,
    only_open_access: bool = False,
    year_filter: Optional[str] = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Run the full discover pipeline, yielding streaming chunks:
    1. {"type": "subqueries", "content": [...]}
    2. {"type": "results", "subquery": "...", "content": [...]}
    3. {"type": "done"}

    Args:
        question: The research question to explore
        sources: Optional list of source keys. "openalex" selects the legacy
                 OpenAlex path; otherwise Scholight MCP is used.
        sort: Optional sort parameter for OpenAlex (e.g., "cited_by_count:desc")
        only_open_access: If True, only return open access papers (OpenAlex only)
        year_filter: Optional time filter ("last_year", "last_5_years", or None for all time)
    """
    # Step 1: Decompose question into subqueries
    subqueries = decompose_query(question)
    yield {"type": "subqueries", "content": subqueries}

    # Determine search strategy based on sources.
    use_openalex = sources and "openalex" in sources
    # Calculate start date for date filtering
    start_date = None
    if year_filter == "last_year":
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    elif year_filter == "last_5_years":
        start_date = (datetime.now() - timedelta(days=5 * 365)).strftime("%Y-%m-%d")

    # Step 2: Search each subquery
    for subquery in subqueries:
        try:
            if use_openalex:
                content = [
                    result.to_dict()
                    for result in search_openalex(
                        subquery,
                        num_results=10,
                        sort=sort,
                        only_open_access=only_open_access,
                        year_filter=year_filter,
                    )
                ]
            else:
                selected = sources or []
                content = []
                if not selected or "scholight" in selected:
                    content.extend(
                        result.to_dict()
                        for result in await search_scholight(
                            subquery,
                            num_results=10,
                            date_from=start_date,
                        )
                    )
                domains = [
                    domain
                    for source in selected
                    if source != "scholight"
                    for domain in (DISCOVER_SOURCES[source]["domains"] or [])
                ]
                if not selected or domains:
                    content.extend(
                        result.to_dict()
                        for result in await search_anysearch(
                            subquery,
                            num_results=10,
                            domains=domains or None,
                        )
                    )

            yield {
                "type": "results",
                "subquery": subquery,
                "content": content,
            }
        except Exception as e:
            logger.error(f"Search failed for subquery '{subquery}': {e}")
            yield {
                "type": "results",
                "subquery": subquery,
                "content": [],
            }

    yield {"type": "done"}
