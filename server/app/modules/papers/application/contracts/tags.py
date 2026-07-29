from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LibraryTagCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    color: str | None = Field(default=None, max_length=64)


class LibraryTagResponse(BaseModel):
    id: UUID
    name: str
    color: str | None


class LibraryTagListResponse(BaseModel):
    items: list[LibraryTagResponse]
    next_cursor: str | None = None


class LibraryTagAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_ids: list[UUID] = Field(min_length=1, max_length=120)
    tag_ids: list[UUID] = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def reject_duplicates(self) -> LibraryTagAssignmentRequest:
        if len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("document_ids must be unique")
        if len(set(self.tag_ids)) != len(self.tag_ids):
            raise ValueError("tag_ids must be unique")
        return self


class LibraryTagAssignmentResponse(BaseModel):
    assigned_count: int
