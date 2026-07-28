"""Explicit public representations for persisted domain objects.

Database models intentionally do not provide a generic serializer. Adding a column to
the database must not silently add it to an HTTP response.
"""

from datetime import datetime
from uuid import UUID

from app.database.models import (
    JsonValue,
    Message,
    Onboarding,
    PaperImage,
    Project,
)
from pydantic import BaseModel, ConfigDict


class OrmResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    def to_json(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json")


class ProjectResponse(OrmResponse):
    id: UUID
    title: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime


class PaperImageResponse(OrmResponse):
    id: UUID
    paper_id: UUID
    s3_object_key: str
    format: str
    size_bytes: int
    width: int
    height: int
    page_number: int
    image_index: int
    caption: str | None
    placeholder_id: str | None
    created_at: datetime
    updated_at: datetime


class OnboardingResponse(OrmResponse):
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


class MessageResponse(OrmResponse):
    id: UUID
    role: str
    content: str
    references: dict[str, JsonValue] | None
    artifacts: list[dict[str, JsonValue]] | None
    trace: dict[str, JsonValue] | None
    scope: list[dict[str, JsonValue]] | None
    sequence: int


def serialize_project(project: Project) -> dict[str, JsonValue]:
    return ProjectResponse.model_validate(project).to_json()


def serialize_paper_image(image: PaperImage) -> dict[str, JsonValue]:
    return PaperImageResponse.model_validate(image).to_json()


def serialize_onboarding(onboarding: Onboarding) -> dict[str, JsonValue]:
    return OnboardingResponse.model_validate(onboarding).to_json()


def serialize_messages(messages: list[Message]) -> list[dict[str, JsonValue]]:
    return [
        MessageResponse.model_validate(
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "references": message.references,
                "artifacts": [
                    item.citation.snapshot
                    for item in message.research_items
                    if item.citation is not None
                ]
                or None,
                "trace": message.trace,
                "scope": message.scope,
                "sequence": message.sequence,
            }
        ).to_json()
        for message in messages
    ]
