"""Typed server-validated material and source contracts for Agent grounding."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from app.shared.domain import JsonValue
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class DocumentAnswerSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: int = Field(ge=1)
    kind: Literal["document"] = "document"
    document_id: UUID
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    reference: str = Field(min_length=1)
    locator: dict[str, JsonValue] | None = None


class ExternalAnswerSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: int = Field(ge=1)
    kind: Literal["external"] = "external"
    url: HttpUrl
    title: str | None = None
    reference: str = Field(min_length=1)


AnswerSource = Annotated[
    DocumentAnswerSource | ExternalAnswerSource,
    Field(discriminator="kind"),
]


class UserMessageReference(BaseModel):
    """A source text explicitly attached by the user, never model-citable."""

    model_config = ConfigDict(extra="forbid")

    key: int = Field(ge=1)
    kind: Literal["user"] = "user"
    reference: str = Field(min_length=1)


MessageReference = Annotated[
    DocumentAnswerSource | ExternalAnswerSource | UserMessageReference,
    Field(discriminator="kind"),
]


class AnswerMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    content: JsonValue
    source_keys: list[int] = Field(default_factory=list)


class AnswerCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observations_total: int = Field(ge=0)
    observations_processed: int = Field(ge=0)
    truncated_observations: int = Field(ge=0)
    truncated_materials: int = Field(ge=0)
    truncated_sources: int = Field(ge=0)
    truncated_actions: int = Field(ge=0)
    context_truncated: bool = False
    rejected_sources: int = Field(ge=0)
    failed_observations: int = Field(ge=0)


class AnswerPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: dict[str, JsonValue]
    materials: list[AnswerMaterial]
    actions: list[dict[str, JsonValue]]
    sources: list[AnswerSource]
    coverage: AnswerCoverage


class CitationAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    source_keys: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_span(self) -> "CitationAnnotation":
        if self.start_offset >= self.end_offset:
            raise ValueError("citation annotation must cover a non-empty text span")
        if any(key < 1 for key in self.source_keys):
            raise ValueError("citation source keys must be positive")
        if len(set(self.source_keys)) != len(self.source_keys):
            raise ValueError("citation source keys must be unique")
        return self


class ReferenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    annotations: list[CitationAnnotation] = Field(default_factory=list)
    sources: list[MessageReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_source_keys(self) -> "ReferenceBundle":
        keys = [source.key for source in self.sources]
        if len(set(keys)) != len(keys):
            raise ValueError("reference source keys must be unique")
        available = set(keys)
        if any(
            key not in available
            for annotation in self.annotations
            for key in annotation.source_keys
        ):
            raise ValueError("citation annotation references an unknown source key")
        return self
