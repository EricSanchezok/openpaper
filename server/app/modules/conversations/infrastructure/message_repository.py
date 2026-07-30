from datetime import datetime, timezone
from uuid import UUID

from app.helpers.postgres import sanitize_for_postgres
from app.database.models import Conversation, Message, RoleType
from app.shared.domain import JsonValue
from app.shared.domain import AppError, FailureKind
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    turn_id: UUID
    created_operation_id: UUID
    correlation_id: UUID
    role: RoleType
    content: str
    references: dict[str, JsonValue] | None = None
    trace: dict[str, JsonValue] | None = None
    # Denormalized @-mention context snapshot: [{kind, id, title}].
    scope: list[dict[str, JsonValue]] | None = None


class MessageRepository:
    """Persistence for messages owned through their parent Conversation."""

    def lock_conversation(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        user_id: int,
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

    def create(
        self,
        db: Session,
        *,
        request: MessageCreate,
        user_id: int,
        refresh_result: bool = True,
    ) -> Message:
        """Create a new message with auto-incrementing sequence number"""
        # Lock the owning conversation so concurrent streams cannot allocate the
        # same sequence number or attach a message to another user's chat.
        conversation = self.lock_conversation(
            db,
            conversation_id=request.conversation_id,
            user_id=user_id,
        )

        max_sequence = db.scalar(
            select(func.max(Message.sequence)).where(
                Message.conversation_id == request.conversation_id,
            )
        )
        next_sequence = (max_sequence or 0) + 1

        # Convert Pydantic model to dict and add sequence. Strip NUL (0x00)
        # characters that PostgreSQL cannot store — message content/references
        # are derived from extracted PDF text, which can contain them. This
        # NUL bytes from extracted PDF text cannot be stored by PostgreSQL.
        request_data = sanitize_for_postgres(request.model_dump(exclude_unset=True))
        db_obj = Message(**request_data, sequence=next_sequence)
        conversation.updated_at = datetime.now(timezone.utc)

        db.add(db_obj)
        if refresh_result:
            db.flush()
            db.refresh(db_obj)
        else:
            db.flush()
        return db_obj

    def find_turn_message(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        user_id: int,
        turn_id: UUID,
        role: RoleType,
    ) -> Message | None:
        return db.scalar(
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.conversation_id == conversation_id,
                Conversation.user_id == user_id,
                Message.turn_id == turn_id,
                Message.role == role.value,
            )
        )

    def get_conversation_messages(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        user_id: int,
        page: int = 1,
        page_size: int = 10,
        exclude_turn_id: UUID | None = None,
    ) -> list[Message]:
        """
        Get messages for a conversation:
        1. Order by sequence DESC for correct pagination (most recent first)
        2. Apply offset and limit
        3. Reverse final results for chronological display
        """
        statement = (
            select(Message)
            .options(selectinload(Message.research_items))
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.conversation_id == conversation_id,
                Conversation.user_id == user_id,
            )
            .order_by(desc(Message.sequence))  # newest first for pagination
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        if exclude_turn_id is not None:
            statement = statement.where(Message.turn_id != exclude_turn_id)
        messages = db.scalars(statement).all()

        # Reverse the results to get chronological order
        return list(reversed(messages))

    def list_conversation_messages(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        user_id: int,
        offset: int,
        limit: int,
    ) -> list[Message]:
        """Return a newest-first page, presented in chronological order."""
        messages = db.scalars(
            select(Message)
            .options(selectinload(Message.research_items))
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.conversation_id == conversation_id,
                Conversation.user_id == user_id,
            )
            .order_by(desc(Message.sequence))
            .offset(offset)
            .limit(limit)
        ).all()
        return list(reversed(messages))


message_repository = MessageRepository()
