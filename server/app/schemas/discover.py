"""Schemas for the Discover feature."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    "arxiv": {
        "label": "arXiv",
        "description": "Preprints in physics, math, CS, and more",
        "domains": ["arxiv.org"],
    },
    "pubmed": {
        "label": "PubMed",
        "description": "Biomedical and life sciences",
        "domains": ["pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov"],
    },
    "nature": {
        "label": "Nature",
        "description": "Nature family of journals",
        "domains": ["nature.com"],
    },
    "science": {
        "label": "Science",
        "description": "Science family of journals",
        "domains": ["science.org"],
    },
    "plos": {
        "label": "PLOS",
        "description": "Open access journals",
        "domains": ["plos.org"],
    },
    "biorxiv": {
        "label": "bioRxiv / medRxiv",
        "description": "Biology and medicine preprints",
        "domains": ["biorxiv.org", "medrxiv.org"],
    },
    "ssrn": {
        "label": "SSRN",
        "description": "Social sciences research",
        "domains": ["ssrn.com"],
    },
    "ieee": {
        "label": "IEEE",
        "description": "Engineering and technology",
        "domains": ["ieee.org", "ieeexplore.ieee.org"],
    },
    "acm": {
        "label": "ACM",
        "description": "Computing and information technology",
        "domains": ["acm.org", "dl.acm.org"],
    },
}


class DiscoverSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=10_000)
    sources: Optional[list[str]] = Field(default=None, max_length=10)
    sort: Optional[str] = Field(
        default=None, pattern="^(cited_by_count:desc|publication_date:desc)$"
    )
    only_open_access: bool = False
    year_filter: Optional[str] = Field(
        default=None, pattern="^(last_year|last_5_years)$"
    )

    @field_validator("sources")
    @classmethod
    def validate_sources(_cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(
            source not in DISCOVER_SOURCES for source in value
        ):
            raise ValueError("Unknown Discover source")
        return value
