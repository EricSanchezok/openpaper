"""Stable DTOs for external scholarly discovery."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


def _abstract_from_inverted_index(index: dict[str, list[int]]) -> str:
    if not index:
        return ""
    positions = [
        (position, word)
        for word, word_positions in index.items()
        for position in word_positions
    ]
    positions.sort()
    return " ".join(word for _, word in positions)


class OAStatus(str, Enum):
    DIAMOND = "diamond"
    GOLDEN = "gold"
    GREEN = "green"
    HYBRID = "hybrid"
    BRONZE = "bronze"
    CLOSED = "closed"


class BaseOpenAlexModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class OpenAccess(BaseOpenAlexModel):
    is_oa: bool
    oa_status: OAStatus | None = None
    oa_url: str | None = None


class Keyword(BaseOpenAlexModel):
    id: str
    display_name: str
    score: float | None = None


class PrimaryLocationSource(BaseOpenAlexModel):
    id: str | None = None
    display_name: str | None = None
    type: str | None = None
    issn_l: str | None = None
    issn: list[str] | None = None
    host_organization: str | None = None


class PrimaryLocation(BaseOpenAlexModel):
    is_oa: bool | None = None
    landing_page_url: str | None = None
    pdf_url: str | None = None
    source: PrimaryLocationSource | None = None


class Biblio(BaseOpenAlexModel):
    volume: str | None = None
    issue: str | None = None
    first_page: str | None = None
    last_page: str | None = None


class SubTopic(BaseOpenAlexModel):
    id: str
    display_name: str


class Topic(BaseOpenAlexModel):
    id: str
    display_name: str | None = None
    score: float | None = None
    subfield: SubTopic | None = None
    field: SubTopic | None = None
    domain: SubTopic | None = None


class Author(BaseOpenAlexModel):
    id: str | None = None
    display_name: str | None = None
    orcid: str | None = None


class Institution(BaseOpenAlexModel):
    id: str | None = None
    display_name: str | None = None
    ror: str | None = None
    country_code: str | None = None
    type: str | None = None


class Authorship(BaseOpenAlexModel):
    author_position: str | None = None
    author: Author | None = None
    institutions: list[Institution] | None = None


class OpenAlexWork(BaseOpenAlexModel):
    id: str
    title: str
    doi: str | None = None
    display_name: str | None = None
    publication_year: int | None = None
    publication_date: str | None = None
    type: str | None = None
    open_access: OpenAccess | None = None
    keywords: list[Keyword] | None = None
    primary_location: PrimaryLocation | None = None
    biblio: Biblio | None = None
    topics: list[Topic] | None = None
    authorships: list[Authorship] | None = None
    cited_by_count: int | None = None
    abstract_inverted_index: dict[str, list[int]] | None = None
    abstract: str | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_abstract(_cls, data: Any) -> Any:
        if (
            isinstance(data, dict)
            and data.get("abstract_inverted_index")
            and not data.get("abstract")
        ):
            data = dict(data)
            data["abstract"] = _abstract_from_inverted_index(
                data["abstract_inverted_index"]
            )
        return data


class OpenAlexResponse(BaseModel):
    meta: dict[str, object]
    results: list[OpenAlexWork]

    @model_validator(mode="before")
    @classmethod
    def discard_invalid_results(_cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            data = dict(data)
            data["results"] = [
                parsed
                for item in data["results"]
                if (parsed := _try_parse_work(item)) is not None
            ]
        return data


class DiscoveryPaperListResponse(BaseModel):
    items: list[OpenAlexWork]
    next_cursor: str | None = None


def _try_parse_work(item: object) -> OpenAlexWork | None:
    try:
        return OpenAlexWork.model_validate(item)
    except (TypeError, ValueError):
        return None


class OpenAlexCitationGraph(BaseModel):
    center: OpenAlexWork
    cites: OpenAlexResponse
    cited_by: OpenAlexResponse


class OpenAlexFilter(BaseModel):
    authors: list[str] | None = None
    institutions: list[str] | None = None
    only_oa: bool = False
    from_publication_date: str | None = None
    min_cited_by_count: int | None = None


class EnrichedData(BaseModel):
    publisher: str | None
    journal: str | None
    publication_date: str | None
