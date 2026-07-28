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
