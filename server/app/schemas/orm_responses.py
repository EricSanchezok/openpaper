"""Explicit public representations for persisted domain objects.

Database models intentionally do not provide a generic serializer. Adding a column to
the database must not silently add it to an HTTP response.
"""

from datetime import datetime
from uuid import UUID

from app.database.models import (
    Annotation,
    Conversation,
    Highlight,
    JsonValue,
    Onboarding,
    Paper,
    PaperImage,
    PaperNote,
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


class PaperNoteResponse(OrmResponse):
    id: UUID
    paper_id: UUID
    content: str
    created_at: datetime
    updated_at: datetime


class ConversationResponse(OrmResponse):
    id: UUID
    title: str | None
    conversable_id: UUID | None
    conversable_type: str
    created_at: datetime
    updated_at: datetime


class HighlightResponse(OrmResponse):
    id: UUID
    paper_id: UUID
    raw_text: str
    type: str | None
    start_offset: int | None
    end_offset: int | None
    page_number: int | None
    position: dict[str, JsonValue] | None
    role: str
    color: str | None
    created_at: datetime
    updated_at: datetime


class AnnotationResponse(OrmResponse):
    id: UUID
    highlight_id: UUID
    paper_id: UUID
    content: str
    role: str
    created_at: datetime
    updated_at: datetime


class PaperImageResponse(OrmResponse):
    id: UUID
    paper_id: UUID
    image_url: str
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
    referral_source: str | None
    referral_source_other: str | None
    created_at: datetime
    updated_at: datetime


class PaperResponse(OrmResponse):
    id: UUID
    status: str
    file_url: str
    preview_url: str | None
    authors: list[str] | None
    title: str | None
    abstract: str | None
    institutions: list[str] | None
    summary: str | None
    summary_citations: list[dict[str, JsonValue]] | None
    publish_date: datetime | None
    starter_questions: list[str] | None
    raw_content: str | None
    parser_quality: str | None
    parser_warning_code: str | None
    page_offset_map: dict[int, list[int]] | None
    last_accessed_at: datetime
    upload_job_id: UUID | None
    is_public: bool | None
    share_id: str | None
    doi: str | None
    journal: str | None
    publisher: str | None
    size_in_kb: int | None
    parent_paper_id: UUID | None
    created_at: datetime
    updated_at: datetime


def serialize_project(project: Project) -> dict[str, JsonValue]:
    return ProjectResponse.model_validate(project).to_json()


def serialize_paper_note(note: PaperNote) -> dict[str, JsonValue]:
    return PaperNoteResponse.model_validate(note).to_json()


def serialize_conversation(conversation: Conversation) -> dict[str, JsonValue]:
    return ConversationResponse.model_validate(conversation).to_json()


def serialize_highlight(highlight: Highlight) -> dict[str, JsonValue]:
    return HighlightResponse.model_validate(highlight).to_json()


def serialize_annotation(annotation: Annotation) -> dict[str, JsonValue]:
    return AnnotationResponse.model_validate(annotation).to_json()


def serialize_paper_image(image: PaperImage) -> dict[str, JsonValue]:
    return PaperImageResponse.model_validate(image).to_json()


def serialize_onboarding(onboarding: Onboarding) -> dict[str, JsonValue]:
    return OnboardingResponse.model_validate(onboarding).to_json()


def serialize_paper(paper: Paper) -> dict[str, JsonValue]:
    return PaperResponse.model_validate(paper).to_json()
