from uuid import UUID

from pydantic import BaseModel, ConfigDict, HttpUrl


class UploadFromUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl


class UploadAcceptedResponse(BaseModel):
    message: str = "File upload started"
    job_id: UUID
