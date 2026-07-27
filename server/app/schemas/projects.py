from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.schemas.citation import CitationData, CitationMethod
from app.schemas.research import ResearchCreatorResponse
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


class ProjectCitationArtifactPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["citation"]
    paper_id: str
    preferred_style: str
    style_display: str
    data: CitationData
    method: CitationMethod
    missing_fields: list[str] = Field(default_factory=list)
    confidence: float | None = None


class ProjectArtifactResponse(BaseModel):
    id: UUID
    kind: Literal["citation"]
    payload: ProjectCitationArtifactPayload
    is_shared: bool
    created_by: ResearchCreatorResponse | None
    created_at: datetime


class ProjectArtifactListResponse(BaseModel):
    artifacts: list[ProjectArtifactResponse]
