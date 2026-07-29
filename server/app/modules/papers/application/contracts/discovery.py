from pydantic import BaseModel


class EnrichedData(BaseModel):
    publisher: str | None
    journal: str | None
    publication_date: str | None
