"""Persistence for conversation turns and their generated response variants."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from app.database.models import Conversation, ConversationResponse, ConversationTurn
from app.helpers.postgres import sanitize_for_postgres
from app.modules.conversations.application.contracts.turns import ConversationTrace
from app.shared.domain import AppError, FailureKind, JsonValue
from sqlalchemy import delete, desc, func, select
from sqlalchemy.orm import Session, selectinload


class TurnRepository:
    def lock_conversation(
        self, db: Session, *, conversation_id: UUID, user_id: int
    ) -> Conversation:
        conversation = db.scalar(
            select(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
            .with_for_update()
        )
        if conversation is None:
            raise AppError(
                code="conversation_not_found",
                message="Conversation not found",
                kind=FailureKind.NOT_FOUND,
            )
        return conversation

    def create_turn(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        turn_id: UUID,
        user_id: int,
        created_operation_id: UUID,
        correlation_id: UUID,
        user_query: str,
        user_references: dict[str, JsonValue] | None,
        scope: list[dict[str, JsonValue]] | None,
        reasoning_level: str,
        locale: str,
        time_zone: str,
    ) -> tuple[ConversationTurn, bool]:
        conversation = self.lock_conversation(
            db, conversation_id=conversation_id, user_id=user_id
        )
        existing = db.scalar(
            select(ConversationTurn).where(
                ConversationTurn.id == turn_id,
                ConversationTurn.conversation_id == conversation_id,
            )
        )
        normalized_query = sanitize_for_postgres(user_query)
        if existing is not None:
            if existing.user_query != normalized_query:
                raise AppError(
                    code="conversation_turn_conflict",
                    message="This conversation turn was already used differently",
                    kind=FailureKind.CONFLICT,
                )
            return existing, False

        previous = db.scalar(
            select(ConversationTurn)
            .where(ConversationTurn.conversation_id == conversation_id)
            .order_by(desc(ConversationTurn.sequence))
            .limit(1)
            .with_for_update()
        )
        if previous is not None:
            selected = (
                db.get(ConversationResponse, previous.selected_response_id)
                if previous.selected_response_id is not None
                else None
            )
            if previous.selected_response_id is not None:
                db.execute(
                    delete(ConversationResponse).where(
                        ConversationResponse.turn_id == previous.id,
                        ConversationResponse.id != previous.selected_response_id,
                    )
                )
            if selected is not None:
                selected.suggestions = None
                selected.suggestions_status = "idle"

        max_sequence = db.scalar(
            select(func.max(ConversationTurn.sequence)).where(
                ConversationTurn.conversation_id == conversation_id
            )
        )
        turn = ConversationTurn(
            id=turn_id,
            conversation_id=conversation_id,
            created_operation_id=created_operation_id,
            correlation_id=correlation_id,
            user_query=normalized_query,
            user_references=sanitize_for_postgres(user_references),
            scope=sanitize_for_postgres(scope),
            reasoning_level=reasoning_level,
            locale=locale,
            time_zone=time_zone,
            sequence=(max_sequence or 0) + 1,
        )
        conversation.updated_at = datetime.now(timezone.utc)
        db.add(turn)
        db.flush()
        return turn, True

    def require_turn(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        turn_id: UUID,
        user_id: int,
        lock: bool = False,
    ) -> ConversationTurn:
        statement = (
            select(ConversationTurn)
            .join(Conversation, Conversation.id == ConversationTurn.conversation_id)
            .where(
                ConversationTurn.id == turn_id,
                ConversationTurn.conversation_id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        if lock:
            statement = statement.with_for_update()
        turn = db.scalar(statement)
        if turn is None:
            raise AppError(
                code="conversation_turn_not_found",
                message="Conversation turn not found",
                kind=FailureKind.NOT_FOUND,
            )
        return turn

    def create_response(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
        user_id: int,
        created_operation_id: UUID,
        correlation_id: UUID,
        generation_kind: Literal["initial", "retry"],
    ) -> tuple[ConversationResponse, bool]:
        self.lock_conversation(db, conversation_id=conversation_id, user_id=user_id)
        turn = self.require_turn(
            db,
            conversation_id=conversation_id,
            turn_id=turn_id,
            user_id=user_id,
            lock=True,
        )
        existing = db.get(ConversationResponse, response_id)
        if existing is not None:
            if existing.turn_id != turn.id:
                raise AppError(
                    code="conversation_response_conflict",
                    message="Response identifier already belongs to another turn",
                    kind=FailureKind.CONFLICT,
                )
            return existing, False

        if generation_kind == "retry":
            latest_turn_id = db.scalar(
                select(ConversationTurn.id)
                .where(ConversationTurn.conversation_id == conversation_id)
                .order_by(desc(ConversationTurn.sequence))
                .limit(1)
            )
            if latest_turn_id != turn.id:
                raise AppError(
                    code="conversation_retry_not_latest",
                    message="Only the latest turn can be retried",
                    kind=FailureKind.CONFLICT,
                )
        running = db.scalar(
            select(ConversationResponse.id).where(
                ConversationResponse.turn_id == turn.id,
                ConversationResponse.status == "running",
            )
        )
        if running is not None:
            raise AppError(
                code="conversation_response_in_progress",
                message="A response is already being generated for this turn",
                kind=FailureKind.CONFLICT,
            )
        max_variant = db.scalar(
            select(func.max(ConversationResponse.variant_index)).where(
                ConversationResponse.turn_id == turn.id
            )
        )
        response = ConversationResponse(
            id=response_id,
            turn_id=turn.id,
            created_operation_id=created_operation_id,
            correlation_id=correlation_id,
            variant_index=(max_variant or 0) + 1,
            status="running",
        )
        db.add(response)
        db.flush()
        return response, True

    def complete_response(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        response_id: UUID,
        user_id: int,
        content: str,
        references: dict[str, JsonValue] | None,
        trace: ConversationTrace | None,
    ) -> ConversationResponse:
        self.lock_conversation(db, conversation_id=conversation_id, user_id=user_id)
        response = db.scalar(
            select(ConversationResponse)
            .join(ConversationTurn, ConversationTurn.id == ConversationResponse.turn_id)
            .where(
                ConversationResponse.id == response_id,
                ConversationTurn.conversation_id == conversation_id,
            )
            .with_for_update()
        )
        if response is None:
            raise AppError(
                code="conversation_response_not_found",
                message="Conversation response not found",
                kind=FailureKind.NOT_FOUND,
            )
        if response.status == "completed":
            return response
        response.status = "completed"
        response.content = sanitize_for_postgres(content)
        response.references = sanitize_for_postgres(references)
        response.trace = sanitize_for_postgres(
            trace.model_dump(mode="json") if trace is not None else None
        )
        response.turn.selected_response_id = response.id
        db.flush()
        return response

    def finish_response(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        response_id: UUID,
        user_id: int,
        status: str,
    ) -> None:
        if status not in {"failed", "cancelled"}:
            raise ValueError("unfinished responses may only fail or be cancelled")
        self.lock_conversation(db, conversation_id=conversation_id, user_id=user_id)
        response = db.scalar(
            select(ConversationResponse)
            .join(ConversationTurn, ConversationTurn.id == ConversationResponse.turn_id)
            .where(
                ConversationResponse.id == response_id,
                ConversationTurn.conversation_id == conversation_id,
            )
            .with_for_update()
        )
        if response is not None and response.status == "running":
            response.status = status
            db.flush()

    def select_response(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
        user_id: int,
    ) -> ConversationResponse:
        self.lock_conversation(db, conversation_id=conversation_id, user_id=user_id)
        turn = self.require_turn(
            db,
            conversation_id=conversation_id,
            turn_id=turn_id,
            user_id=user_id,
            lock=True,
        )
        latest_turn_id = db.scalar(
            select(ConversationTurn.id)
            .where(ConversationTurn.conversation_id == conversation_id)
            .order_by(desc(ConversationTurn.sequence))
            .limit(1)
        )
        if latest_turn_id != turn.id:
            raise AppError(
                code="conversation_selection_not_latest",
                message="Only the latest turn can switch response variants",
                kind=FailureKind.CONFLICT,
            )
        response = db.scalar(
            select(ConversationResponse).where(
                ConversationResponse.id == response_id,
                ConversationResponse.turn_id == turn.id,
                ConversationResponse.status == "completed",
            )
        )
        if response is None:
            raise AppError(
                code="conversation_response_not_selectable",
                message="Conversation response cannot be selected",
                kind=FailureKind.CONFLICT,
            )
        turn.selected_response_id = response.id
        db.flush()
        return response

    def require_response(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        response_id: UUID,
        user_id: int,
    ) -> ConversationResponse:
        response = db.scalar(
            select(ConversationResponse)
            .options(selectinload(ConversationResponse.turn))
            .join(ConversationTurn, ConversationTurn.id == ConversationResponse.turn_id)
            .join(Conversation, Conversation.id == ConversationTurn.conversation_id)
            .where(
                ConversationResponse.id == response_id,
                ConversationTurn.conversation_id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        if response is None:
            raise AppError(
                code="conversation_response_not_found",
                message="Conversation response not found",
                kind=FailureKind.NOT_FOUND,
            )
        return response

    def latest_turn_id(
        self, db: Session, *, conversation_id: UUID, user_id: int
    ) -> UUID | None:
        return db.scalar(
            select(ConversationTurn.id)
            .join(Conversation, Conversation.id == ConversationTurn.conversation_id)
            .where(
                ConversationTurn.conversation_id == conversation_id,
                Conversation.user_id == user_id,
            )
            .order_by(desc(ConversationTurn.sequence))
            .limit(1)
        )

    def list_turns(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        user_id: int,
        offset: int,
        limit: int,
    ) -> list[ConversationTurn]:
        turns = db.scalars(
            select(ConversationTurn)
            .options(
                selectinload(ConversationTurn.responses).selectinload(
                    ConversationResponse.research_items
                )
            )
            .join(Conversation, Conversation.id == ConversationTurn.conversation_id)
            .where(
                ConversationTurn.conversation_id == conversation_id,
                Conversation.user_id == user_id,
            )
            .order_by(desc(ConversationTurn.sequence))
            .offset(offset)
            .limit(limit)
        ).all()
        return list(reversed(turns))

    def history(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        user_id: int,
        exclude_turn_id: UUID | None = None,
    ) -> list[ConversationTurn]:
        statement = (
            select(ConversationTurn)
            .options(selectinload(ConversationTurn.responses))
            .join(Conversation, Conversation.id == ConversationTurn.conversation_id)
            .where(
                ConversationTurn.conversation_id == conversation_id,
                Conversation.user_id == user_id,
                ConversationTurn.selected_response_id.is_not(None),
            )
            .order_by(ConversationTurn.sequence)
        )
        if exclude_turn_id is not None:
            statement = statement.where(ConversationTurn.id != exclude_turn_id)
        return list(db.scalars(statement).all())


turn_repository = TurnRepository()
