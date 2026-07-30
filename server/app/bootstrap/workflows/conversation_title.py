"""Generate a Conversation title without holding a database transaction."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.llm.conversation_operations import ConversationOperations
from app.modules.conversations.application.contracts.conversations import (
    ConversationAutoTitleResponse,
)
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)
from app.shared.domain import AppError, FailureKind


class ConversationTitleWorkflow:
    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        generator: ConversationOperations,
        operation_factory: OperationContextFactory,
    ) -> None:
        self._executor = executor
        self._generator = generator
        self._operation_factory = operation_factory

    def run(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
    ) -> ConversationAutoTitleResponse:
        history = self._executor.query(
            lambda capabilities: capabilities.conversation_chat_data.history(
                actor=actor,
                conversation_id=conversation_id,
                exclude_turn_id=None,
            )
        )
        title = self._generator.generate_title(history)
        if not title:
            raise AppError(
                code="conversation_title_failed",
                message="Conversation title could not be generated",
                kind=FailureKind.UNPROCESSABLE,
            )
        title_operation = self._operation_factory.child(
            operation,
            initiated_by=OperationInitiator.AGENT,
        )
        return self._executor.command(
            lambda capabilities: capabilities.conversations.apply_generated_title(
                actor=actor,
                operation=title_operation,
                conversation_id=conversation_id,
                title=title,
            )
        )
