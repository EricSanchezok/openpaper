from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CreateOnboardingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=240)
    email: EmailStr
    company: str | None = Field(default=None, max_length=500)
    research_fields: str | None = Field(default=None, max_length=5_000)
    research_fields_other: str | None = Field(default=None, max_length=2_000)
    job_titles: str | None = Field(default=None, max_length=5_000)
    job_titles_other: str | None = Field(default=None, max_length=2_000)
    reading_frequency: str | None = Field(default=None, max_length=100)


class OnboardingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str | None
    email: str | None
    company: str | None
    research_fields: str | None
    research_fields_other: str | None
    job_titles: str | None
    job_titles_other: str | None
    reading_frequency: str | None
    created_at: datetime
    updated_at: datetime
