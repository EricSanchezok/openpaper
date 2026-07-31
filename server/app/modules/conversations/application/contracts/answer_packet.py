"""Typed material and source contracts consumed by the final answer runtime."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from app.shared.domain import JsonValue
from pydantic import BaseModel, ConfigDict, Field, HttpUrl


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
    rejected_sources: int = Field(ge=0)
    failed_observations: int = Field(ge=0)


class AnswerPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: dict[str, JsonValue]
    materials: list[AnswerMaterial]
    actions: list[dict[str, JsonValue]]
    sources: list[AnswerSource]
    coverage: AnswerCoverage


class MessageReferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citations: list[MessageReference]
