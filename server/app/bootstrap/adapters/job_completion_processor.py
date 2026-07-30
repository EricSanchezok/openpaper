"""Resume authenticated Job causality and own post-commit callback effects."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.workflows.pdf_postprocess import PdfPostprocessWorkflow
from app.bootstrap.workflows.zotero import ZoteroPostprocessWorkflow
from app.database.telemetry import track_event
from app.helpers.ai_limits import release_concurrency_by_id
from app.modules.jobs.application.authentication import VerifiedJobCallback
from app.modules.jobs.application.contracts import (
    JobClaimResponse,
    JobFailureCallback,
)
from app.modules.jobs.application.callbacks import (
    JobCompletionResult,
    JobPostCommitAction,
    RecordJobTelemetry,
    ReleaseJobConcurrency,
    SettleJobUsage,
)
from app.modules.jobs.application.causality import (
    JobCausalityFacts,
    require_job_causality_owner,
)
from app.modules.jobs.infrastructure.causality import (
    SqlAlchemyJobCausalityResolver,
)
from app.modules.jobs.infrastructure.research_callbacks import settle_jobs_usage
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    CredentialKind,
    CredentialRef,
    JobOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)
from app.shared.domain.enums import JobOperation
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ResumedJob:
    actor: Actor | None
    operation: OperationContext


class JobCompletionProcessor:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        executor: ApplicationExecutor[ApplicationCapabilities],
        operation_factory: OperationContextFactory,
        pdf_postprocess: PdfPostprocessWorkflow,
        zotero_postprocess: ZoteroPostprocessWorkflow,
    ) -> None:
        self._session_factory = session_factory
        self._executor = executor
        self._operation_factory = operation_factory
        self._pdf_postprocess = pdf_postprocess
        self._zotero_postprocess = zotero_postprocess

    async def complete(
        self,
        *,
        job_id: UUID,
        payload: dict[str, object],
        verified: VerifiedJobCallback,
    ) -> object:
        facts = self._causality(job_id=job_id)
        resumed = self._resume(facts=facts, verified=verified)
        job_operation = facts.operation
        if job_operation is JobOperation.PDF_POSTPROCESS:
            if resumed.actor is None:
                raise RuntimeError("pdf_postprocess_job_owner_missing")
            result = await self._pdf_postprocess.complete(
                actor=resumed.actor,
                operation=resumed.operation,
                job_id=job_id,
                payload=payload,
            )
            await self._run_post_commit(result)
            return result.value
        if job_operation is JobOperation.ZOTERO_POSTPROCESS:
            return await self._zotero_postprocess.complete(
                actor=resumed.actor,
                operation=resumed.operation,
                job_id=job_id,
                payload=payload,
            )
        result = await self._executor.command_async(
            lambda capabilities: capabilities.job_callbacks.complete(
                actor=resumed.actor,
                operation=resumed.operation,
                job_id=job_id,
                payload=payload,
            )
        )
        await self._run_post_commit(result)
        return result.value

    def fail(
        self,
        *,
        job_id: UUID,
        callback: JobFailureCallback,
        verified: VerifiedJobCallback,
    ) -> JobClaimResponse:
        facts = self._causality(job_id=job_id)
        resumed = self._resume(facts=facts, verified=verified)
        return self._executor.command(
            lambda capabilities: capabilities.job_callbacks.fail(
                actor=resumed.actor,
                operation=resumed.operation,
                job_id=job_id,
                callback=callback,
            )
        )

    def _resume(
        self,
        *,
        facts: JobCausalityFacts,
        verified: VerifiedJobCallback,
    ) -> _ResumedJob:
        requested_by_id = facts.requested_by_id
        actor = (
            self._executor.query(
                lambda capabilities: capabilities.identity.resolve_actor_by_user_id(
                    requested_by_id
                )
            )
            if requested_by_id is not None
            else None
        )
        require_job_causality_owner(facts=facts, actor=actor)
        operation = self._operation_factory.resume(
            correlation_id=facts.correlation_id,
            causation_id=facts.origin_operation_id,
            initiated_by=OperationInitiator.SYSTEM,
            origin=JobOrigin(
                job_id=facts.job_id,
                delivery_ref=verified.delivery_ref,
                request_id=verified.request_id,
            ),
            credential=CredentialRef(CredentialKind.INTERNAL_SIGNATURE),
        )
        return _ResumedJob(actor=actor, operation=operation)

    def _causality(self, *, job_id: UUID) -> JobCausalityFacts:
        with self._session_factory() as session:
            return SqlAlchemyJobCausalityResolver(session).resolve(job_id=job_id)

    async def _run_post_commit(self, result: JobCompletionResult) -> None:
        for action in result.post_commit:
            await _execute_post_commit(action)


async def _execute_post_commit(action: JobPostCommitAction) -> None:
    try:
        if isinstance(action, ReleaseJobConcurrency):
            await release_concurrency_by_id(
                user_id=action.user_id,
                category=action.category,
                operation_id=str(action.job_id),
            )
            return
        if isinstance(action, SettleJobUsage):
            await asyncio.to_thread(
                settle_jobs_usage,
                action.user_id,
                list(action.events),
            )
            return
        if isinstance(action, RecordJobTelemetry):
            track_event(
                action.event,
                properties=dict(action.properties),
                user_id=str(action.actor_id),
            )
            return
        raise TypeError(f"unsupported Job post-commit action: {type(action).__name__}")
    except Exception:
        logger.exception(
            "Job post-commit action failed",
            extra={"action_type": type(action).__name__},
        )


__all__ = ["JobCompletionProcessor"]
