from uuid import UUID

from pydantic import BaseModel


class BulkTagRequest(BaseModel):
    paper_ids: list[UUID]
    tag_ids: list[UUID]


class EnrichedData(BaseModel):
    publisher: str | None
    journal: str | None
    publication_date: str | None
