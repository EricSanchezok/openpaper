"""Schemas for the Discover feature."""

from typing import Optional

from pydantic import BaseModel

# Available search backends for Discover.
DISCOVER_SOURCES = {
    "openalex": {
        "label": "Academic Databases",
        "description": "OpenAlex scholarly index",
        "domains": None,
    },
    "scholight": {
        "label": "Scholight",
        "description": "SanchezCloud ranked academic paper search",
        "domains": None,
    },
}


class DiscoverSearchRequest(BaseModel):
    question: str
    sources: Optional[list[str]] = None  # List of source keys from DISCOVER_SOURCES
    sort: Optional[str] = (
        None  # Sort option: "cited_by_count:desc" or "publication_date:desc"
    )
    only_open_access: bool = False  # Filter for open access papers (OpenAlex only)
    year_filter: Optional[str] = (
        None  # Time filter: "last_year", "last_5_years", or None for all time
    )
