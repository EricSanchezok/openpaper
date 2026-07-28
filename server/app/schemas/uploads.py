from datetime import datetime
from uuid import UUID

from app.database.models import JobStatus
from pydantic import BaseModel, ConfigDict, HttpUrl


class UploadFromUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl


class UploadAcceptedResponse(BaseModel):
    message: str = "File upload started"
    job_id: UUID


class UploadStatusResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    task_id: UUID | None
    started_at: datetime | None
    completed_at: datetime | None
    has_file: bool
    has_metadata: bool
    paper_id: UUID | None
    parser_quality: str | None
    parser_warning_code: str | None
    progress_message: str | None
    error_code: str | None
