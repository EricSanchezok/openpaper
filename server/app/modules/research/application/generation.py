"""Durable Research generation with replaceable quota and Jobs ports."""

from __future__ import annotations

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
from app.modules.papers.application.content import (
    AccessiblePaperContent,
    PaperContentCapabilities,
)
from app.modules.projects.application.document_visibility import (
    ListAccessibleProjectDocuments,
)
from app.shared.application import Actor
from app.shared.domain import AppError, JsonValue, FailureKind
from app.shared.domain.enums import JobOperation
from pydantic import TypeAdapter

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class GenerationCapacity(Protocol):
    def require_tokens(self, *, actor: Actor) -> None: ...

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


class ResearchGeneration:
    def __init__(
        self,
        *,
        documents: GenerationDocuments,
        jobs: JobCommandPort,
        capacity: GenerationCapacity,
    ) -> None:
        self._documents = documents
        self._jobs = jobs
        self._capacity = capacity

    async def document_audio(
        self,
        *,
        actor: Actor,
        client_ip: str,
        document_id: UUID,
        request: CreateAudioOverviewRequest,
        idempotency_key: str | None,
    ) -> CreateJobResponse:
        return await self._audio(
            actor=actor,
            client_ip=client_ip,
            scope_type="document",
            scope_id=document_id,
            documents=[self._documents.document(actor=actor, document_id=document_id)],
            request=request,
            idempotency_key=idempotency_key,
        )

    async def project_audio(
        self,
        *,
        actor: Actor,
        client_ip: str,
        project_id: UUID,
        request: CreateAudioOverviewRequest,
        idempotency_key: str | None,
    ) -> CreateJobResponse:
        documents = self._documents.project(actor=actor, project_id=project_id)
        if not documents:
            raise AppError(
                code="project_has_no_papers",
                message="Add at least one paper before generating audio",
                kind=FailureKind.CONFLICT,
            )
        return await self._audio(
            actor=actor,
            client_ip=client_ip,
            scope_type="project",
            scope_id=project_id,
            documents=documents,
            request=request,
            idempotency_key=idempotency_key,
        )

    async def _audio(
        self,
        *,
        actor: Actor,
        client_ip: str,
        scope_type: Literal["document", "project"],
        scope_id: UUID,
        documents: list[AccessiblePaperContent],
        request: CreateAudioOverviewRequest,
        idempotency_key: str | None,
    ) -> CreateJobResponse:
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
        self._capacity.require_tokens(actor=actor)
        await self._capacity.enforce_rate(
            actor=actor,
            client_ip=client_ip,
            feature="audio",
        )
        await self._capacity.acquire_audio(actor=actor, operation_id=operation_id)
        try:
            job = self._jobs.enqueue(
                command=EnqueueJobCommand(
                    job_id=operation_id,
                    operation=JobOperation.AUDIO_GENERATE,
                    requested_by_id=actor.id,
                    project_id=scope_id if scope_type == "project" else None,
                    document_id=scope_id if scope_type == "document" else None,
                    idempotency_key=operation_key,
                    payload=payload,
                    task_name="generate_audio_overview",
                    queue="audio",
                )
            )
            if job.id != operation_id:
                await self._capacity.release_audio(
                    actor=actor,
                    operation_id=operation_id,
                )
            return CreateJobResponse(job=job)
        except Exception:
            await self._capacity.release_audio(
                actor=actor,
                operation_id=operation_id,
            )
            raise

    async def project_data_table(
        self,
        *,
        actor: Actor,
        client_ip: str,
        project_id: UUID,
        request: CreateDataTableRequest,
        idempotency_key: str | None,
    ) -> CreateJobResponse:
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
        self._capacity.require_tokens(actor=actor)
        await self._capacity.enforce_rate(
            actor=actor,
            client_ip=client_ip,
            feature="data_table",
        )
        await self._capacity.acquire_background(
            actor=actor,
            operation_id=operation_id,
        )
        try:
            job = self._jobs.enqueue(
                command=EnqueueJobCommand(
                    job_id=operation_id,
                    operation=JobOperation.DATA_TABLE_GENERATE,
                    requested_by_id=actor.id,
                    project_id=project_id,
                    idempotency_key=operation_key,
                    payload=payload,
                    task_name="process_data_table",
                    queue="data_table",
                )
            )
            if job.id != operation_id:
                await self._capacity.release_background(
                    actor=actor,
                    operation_id=operation_id,
                )
            return CreateJobResponse(job=job)
        except Exception:
            await self._capacity.release_background(
                actor=actor,
                operation_id=operation_id,
            )
            raise
