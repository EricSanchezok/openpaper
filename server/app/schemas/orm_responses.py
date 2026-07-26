"""Explicit public representations for persisted domain objects.

Database models intentionally do not provide a generic serializer. Adding a column to
the database must not silently add it to an HTTP response.
"""

from datetime import datetime
from uuid import UUID

from app.database.models import (
    Annotation,
    AudioOverview,
    AudioOverviewJob,
    Conversation,
    DataTableExtractionJob,
    DataTableExtractionResult,
    Highlight,
    JsonValue,
    Message,
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


class MessageResponse(OrmResponse):
    id: UUID
    role: str
    content: str
    references: dict[str, JsonValue] | None
    artifacts: list[dict[str, JsonValue]] | None
    trace: list[dict[str, JsonValue]] | None
    scope: list[dict[str, JsonValue]] | None
    sequence: int


class AudioOverviewJobResponse(OrmResponse):
    id: UUID
    conversable_id: UUID
    conversable_type: str
    status: str
    status_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AudioOverviewResponse(OrmResponse):
    id: UUID
    conversable_id: UUID
    conversable_type: str
    s3_object_key: str
    transcript: str | None
    title: str | None
    citations: list[dict[str, JsonValue]] | None
    created_at: datetime
    updated_at: datetime


class DataTableJobResponse(OrmResponse):
    id: UUID
    project_id: UUID | None
    columns: list[str] | None
    task_id: str | None
    title: str | None
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    error_message: str | None
    result_id: UUID | None


class DataTableRowResponse(OrmResponse):
    id: UUID
    paper_id: UUID
    values: dict[str, JsonValue]


class DataTableResultResponse(OrmResponse):
    id: UUID
    job_id: UUID
    title: str | None
    success: bool
    columns: list[str]
    row_failures: list[UUID]
    created_at: datetime
    updated_at: datetime
    rows: list[DataTableRowResponse] | None = None


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


def serialize_messages(messages: list[Message]) -> list[dict[str, JsonValue]]:
    return [
        MessageResponse.model_validate(
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "references": message.references,
                "artifacts": [artifact.payload for artifact in message.artifacts]
                or None,
                "trace": message.trace,
                "scope": message.scope,
                "sequence": message.sequence,
            }
        ).to_json()
        for message in messages
    ]


def serialize_audio_overview_job(
    job: AudioOverviewJob,
) -> dict[str, JsonValue]:
    return AudioOverviewJobResponse.model_validate(job).to_json()


def serialize_audio_overview(overview: AudioOverview) -> dict[str, JsonValue]:
    return AudioOverviewResponse.model_validate(overview).to_json()


def serialize_data_table_job(
    job: DataTableExtractionJob,
) -> dict[str, JsonValue]:
    return DataTableJobResponse.model_validate(
        {
            "id": job.id,
            "project_id": job.project_id,
            "columns": job.columns,
            "task_id": job.task_id,
            "title": job.result.title if job.result else None,
            "status": job.status,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "error_message": job.error_message,
            "result_id": job.result.id if job.result else None,
        }
    ).to_json()


def serialize_data_table_result(
    result: DataTableExtractionResult,
    *,
    include_rows: bool = True,
) -> dict[str, JsonValue]:
    return DataTableResultResponse.model_validate(
        {
            "id": result.id,
            "job_id": result.job_id,
            "title": result.title,
            "success": result.success,
            "columns": result.columns,
            "row_failures": result.row_failures or [],
            "created_at": result.created_at,
            "updated_at": result.updated_at,
            "rows": result.rows if include_rows else None,
        }
    ).to_json()
