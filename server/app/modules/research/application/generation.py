"""Durable Research generation with replaceable quota and Jobs ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID, uuid4

from app.modules.jobs.application.contracts import (
    AudioOverviewTaskPayload,
    AudioSourceDocumentPayload,
    CreateAudioOverviewRequest,
    CreateDataTableRequest,
    CreateJobResponse,
    DataTableSourceDocumentPayload,
    DataTableTaskPayload,
    DataTableTaskTablePayload,
)
from app.modules.jobs.application.jobs import EnqueueJobCommand, JobCommandPort
from app.modules.jobs.application.actions import JOB_CREATED
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.modules.papers.application.content import (
    AccessiblePaperContent,
    PaperContentCapabilities,
)
from app.modules.projects.application.document_visibility import (
    ListAccessibleProjectDocuments,
)
from app.shared.application import Actor, OperationContext
from app.shared.domain import AppError, JsonValue, FailureKind
from app.shared.domain.enums import JobOperation
from pydantic import TypeAdapter

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])

RESEARCH_AUDIO_OVERVIEW_CREATED = OperationAction("research.audio_overview_created")
RESEARCH_DATA_TABLE_CREATED = OperationAction("research.data_table_created")


class GenerationEntitlements(Protocol):
    def require_tokens(self, *, actor: Actor) -> None: ...


class GenerationCapacity(Protocol):
    async def enforce_rate(
        self,
        *,
        actor: Actor,
        client_ip: str,
        feature: Literal["audio", "data_table"],
    ) -> None: ...

    async def acquire_audio(self, *, actor: Actor, operation_id: UUID) -> None: ...

    async def acquire_background(
        self,
        *,
        actor: Actor,
        operation_id: UUID,
    ) -> None: ...

    async def release_audio(self, *, actor: Actor, operation_id: UUID) -> None: ...

    async def release_background(
        self,
        *,
        actor: Actor,
        operation_id: UUID,
    ) -> None: ...


class GenerationDocuments:
    """Cross-module coordinator that uses public Papers/Projects capabilities."""

    def __init__(
        self,
        *,
        content: PaperContentCapabilities,
        project_documents: ListAccessibleProjectDocuments,
    ) -> None:
        self._content = content
        self._project_documents = project_documents

    def document(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> AccessiblePaperContent:
        return self._content.read(actor=actor, document_id=document_id)

    def project(
        self,
        *,
        actor: Actor,
        project_id: UUID,
    ) -> list[AccessiblePaperContent]:
        return [
            self._content.read(
                actor=actor,
                document_id=document_id,
                project_id=project_id,
            )
            for document_id in self._project_documents(
                actor=actor,
                project_id=project_id,
            )
        ]


def _audio_source(document: AccessiblePaperContent) -> AudioSourceDocumentPayload:
    if not document.parser_markdown_storage_key:
        raise AppError(
            code="document_not_ready",
            message="The document has not finished indexing",
            kind=FailureKind.CONFLICT,
        )
    return AudioSourceDocumentPayload(
        id=document.document_id,
        title=document.title or document.original_filename,
        canonical_s3_key=document.parser_markdown_storage_key,
    )


@dataclass(frozen=True, slots=True)
class PreparedGeneration:
    command: EnqueueJobCommand
    feature: Literal["audio", "data_table"]


class ResearchGeneration:
    def __init__(
        self,
        *,
        documents: GenerationDocuments,
        jobs: JobCommandPort,
        entitlements: GenerationEntitlements,
        journal: OperationJournal,
    ) -> None:
        self._documents = documents
        self._jobs = jobs
        self._entitlements = entitlements
        self._journal = journal

    def prepare_document_audio(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        request: CreateAudioOverviewRequest,
        idempotency_key: str | None,
    ) -> CreateJobResponse | PreparedGeneration:
        return self._prepare_audio(
            actor=actor,
            operation=operation,
            scope_type="document",
            scope_id=document_id,
            documents=[self._documents.document(actor=actor, document_id=document_id)],
            request=request,
            idempotency_key=idempotency_key,
        )

    def prepare_project_audio(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        request: CreateAudioOverviewRequest,
        idempotency_key: str | None,
    ) -> CreateJobResponse | PreparedGeneration:
        documents = self._documents.project(actor=actor, project_id=project_id)
        if not documents:
            raise AppError(
                code="project_has_no_papers",
                message="Add at least one paper before generating audio",
                kind=FailureKind.CONFLICT,
            )
        return self._prepare_audio(
            actor=actor,
            operation=operation,
            scope_type="project",
            scope_id=project_id,
            documents=documents,
            request=request,
            idempotency_key=idempotency_key,
        )

    def _prepare_audio(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        scope_type: Literal["document", "project"],
        scope_id: UUID,
        documents: list[AccessiblePaperContent],
        request: CreateAudioOverviewRequest,
        idempotency_key: str | None,
    ) -> CreateJobResponse | PreparedGeneration:
        operation_id = uuid4()
        operation_key = (
            f"audio:{actor.id}:{scope_type}:{scope_id}:{idempotency_key}"
            if idempotency_key
            else f"audio:{operation_id}"
        )
        existing = self._jobs.find_by_idempotency_key(key=operation_key)
        if existing is not None:
            return CreateJobResponse(job=existing)

        payload_model = AudioOverviewTaskPayload(
            research_item_id=uuid4(),
            scope_type=scope_type,
            scope_id=scope_id,
            documents=[_audio_source(document) for document in documents],
            length=request.length,
            additional_instructions=request.additional_instructions,
        )
        payload = _JSON_OBJECT.validate_python(payload_model.model_dump(mode="json"))
        self._entitlements.require_tokens(actor=actor)
        return PreparedGeneration(
            command=EnqueueJobCommand(
                job_id=operation_id,
                operation=JobOperation.AUDIO_GENERATE,
                requested_by_id=actor.id,
                correlation_id=operation.trace.correlation_id,
                origin_operation_id=operation.trace.operation_id,
                project_id=scope_id if scope_type == "project" else None,
                document_id=scope_id if scope_type == "document" else None,
                idempotency_key=operation_key,
                payload=payload,
                task_name="generate_audio_overview",
                queue="audio",
            ),
            feature="audio",
        )

    def prepare_project_data_table(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        request: CreateDataTableRequest,
        idempotency_key: str | None,
    ) -> CreateJobResponse | PreparedGeneration:
        documents = self._documents.project(actor=actor, project_id=project_id)
        if not documents:
            raise AppError(
                code="project_has_no_papers",
                message="Add at least one paper before generating a data table",
                kind=FailureKind.CONFLICT,
            )
        operation_id = uuid4()
        operation_key = (
            f"data-table:{actor.id}:{project_id}:{idempotency_key}"
            if idempotency_key
            else f"data-table:{operation_id}"
        )
        existing = self._jobs.find_by_idempotency_key(key=operation_key)
        if existing is not None:
            return CreateJobResponse(job=existing)

        payload_model = DataTableTaskPayload(
            research_item_id=uuid4(),
            title=request.title,
            table=DataTableTaskTablePayload(
                columns=request.columns,
                papers=[
                    DataTableSourceDocumentPayload(
                        id=document.document_id,
                        title=document.title or document.original_filename,
                        raw_content=document.raw_content or "",
                    )
                    for document in documents
                ],
            ),
        )
        payload = _JSON_OBJECT.validate_python(payload_model.model_dump(mode="json"))
        self._entitlements.require_tokens(actor=actor)
        return PreparedGeneration(
            command=EnqueueJobCommand(
                job_id=operation_id,
                operation=JobOperation.DATA_TABLE_GENERATE,
                requested_by_id=actor.id,
                correlation_id=operation.trace.correlation_id,
                origin_operation_id=operation.trace.operation_id,
                project_id=project_id,
                idempotency_key=operation_key,
                payload=payload,
                task_name="process_data_table",
                queue="data_table",
            ),
            feature="data_table",
        )

    def enqueue(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        prepared: PreparedGeneration,
    ) -> CreateJobResponse:
        result = self._jobs.enqueue(command=prepared.command)
        if result.created:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=JOB_CREATED,
                resources=(ResourceRef(type="job", id=str(result.job.id)),),
            )
        return CreateJobResponse(job=result.job)
