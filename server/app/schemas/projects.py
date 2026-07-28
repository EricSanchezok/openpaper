from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ProjectPermissionSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edit_project: bool = False
    manage_papers: bool = False
    manage_collaborators: bool = False


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=10_000)


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=10_000)


class ProjectCollaboratorUpdateRequest(ProjectPermissionSet):
    pass


class ProjectInvitationCreateRequest(ProjectPermissionSet):
    email: EmailStr


class ProjectTransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_owner_id: int


class ProjectOwnerResponse(BaseModel):
    id: int
    display_name: str
    email: EmailStr


class ProjectMembershipResponse(BaseModel):
    kind: str
    permissions: ProjectPermissionSet


class ProjectCapabilitiesResponse(BaseModel):
    read: bool = True
    edit_project: bool
    manage_papers: bool
    manage_collaborators: bool
    create_conversation: bool = True
    contribute_research: bool = True
    transfer: bool
    delete: bool
    leave: bool


class ProjectResponse(BaseModel):
    id: UUID
    title: str
    description: str | None
    owner: ProjectOwnerResponse
    membership: ProjectMembershipResponse
    capabilities: ProjectCapabilitiesResponse
    num_papers: int = 0
    num_conversations: int = 0
    num_audio_overviews: int = 0
    num_data_tables: int = 0
    num_collaborators: int = 0
    created_at: datetime
    updated_at: datetime


class ProjectCollaboratorResponse(BaseModel):
    user_id: int
    display_name: str
    email: EmailStr
    is_owner: bool
    permissions: ProjectPermissionSet
    joined_at: datetime | None


class ProjectInvitationResponse(BaseModel):
    id: UUID
    project_id: UUID
    project_name: str
    email: EmailStr
    invited_by: str
    permissions: ProjectPermissionSet
    expires_at: datetime
    created_at: datetime


class ProjectPaperSummaryResponse(BaseModel):
    id: UUID
    title: str | None
    created_at: datetime
    abstract: str | None
    authors: list[str] | None
    institutions: list[str] | None
    status: str
    journal: str | None
    publisher: str | None
    doi: str | None
    publish_date: datetime | None
    file_url: str | None
    in_library: bool


class ProjectPaperListResponse(BaseModel):
    papers: list[ProjectPaperSummaryResponse]


class ProjectPapersAddedResponse(BaseModel):
    added_count: int
    existing_count: int


class ProjectPaperCollectedResponse(BaseModel):
    paper_id: UUID


class ProjectPaperFileUrlResponse(BaseModel):
    file_url: str


class ProjectPendingUploadResponse(BaseModel):
    job_id: UUID
    status: str
    paper_id: UUID
    title: str | None
    started_at: datetime | None


class ProjectPendingUploadsResponse(BaseModel):
    jobs: list[ProjectPendingUploadResponse]
