from typing import Any
from uuid import UUID

from app.database.crud.base_crud import CRUDBase
from app.database.crud.sanitization import sanitize_for_postgres
from app.database.models import Message
from app.schemas.user import CurrentUser
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session


class MessageBase(BaseModel):
    conversation_id: UUID
    role: str
    content: str
    references: dict[str, Any] | None = None
    trace: dict[str, Any] | None = None
    # Denormalized @-mention context snapshot: [{kind, id, title}].
    scope: list[dict[str, Any]] | None = None


class MessageCreate(MessageBase):
    pass


class MessageUpdate(BaseModel):
    role: str | None = None
    content: str | None = None
    references: dict[str, Any] | None = None
    trace: dict[str, Any] | None = None
    scope: list[dict[str, Any]] | None = None


class MessageCRUD(CRUDBase[Message, MessageCreate, MessageUpdate]):
    """CRUD operations specifically for Message model"""

    def create(
        self,
        db: Session,
        *,
        obj_in: MessageCreate,
        user: CurrentUser | None = None,
        auto_commit: bool = True,
    ) -> Message | None:
        """Create a new message with auto-incrementing sequence number"""
        if user is None:
            raise ValueError("User must be provided to create a message")
        # Get the next sequence number for this conversation
        max_sequence = db.scalar(
            select(func.max(Message.sequence)).where(
                Message.conversation_id == obj_in.conversation_id,
                Message.user_id == user.id,
            )
        )
        next_sequence = (max_sequence or 0) + 1

        # Convert Pydantic model to dict and add sequence. Strip NUL (0x00)
        # characters that PostgreSQL cannot store — message content/references
        # are derived from extracted PDF text, which can contain them. This
        # mirrors the sanitization base_crud applies; without it, a NUL byte
        # fails the flush and poisons the shared session.
        obj_in_data = sanitize_for_postgres(obj_in.model_dump(exclude_unset=True))
        db_obj = Message(**obj_in_data, sequence=next_sequence, user_id=user.id)

        try:
            db.add(db_obj)
            if auto_commit:
                db.commit()
                db.refresh(db_obj)
            else:
                db.flush()
        except Exception:
            # Roll back so a failed flush doesn't leave the session in a
            # PendingRollbackError state for every later operation.
            db.rollback()
            raise
        return db_obj

    def get_conversation_messages(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        current_user: CurrentUser,
        page: int = 1,
        page_size: int = 10,
    ) -> list[Message]:
        """
        Get messages for a conversation:
        1. Order by sequence DESC for correct pagination (most recent first)
        2. Apply offset and limit
        3. Reverse final results for chronological display
        """
        messages = db.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.user_id == current_user.id,
            )
            .order_by(desc(Message.sequence))  # newest first for pagination
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()

        # Reverse the results to get chronological order
        return list(reversed(messages))

    def resequence_messages(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        current_user: CurrentUser,
        gap: int = 10,
    ) -> None:
        """
        Resequence all messages in a conversation with specified gaps
        Useful when needing to insert messages between existing ones
        """
        messages = self.get_conversation_messages(
            db, conversation_id=conversation_id, current_user=current_user
        )
        for i, message in enumerate(messages):
            message.sequence = (i + 1) * gap
        db.commit()


# Create a single instance to use throughout the application
message_crud = MessageCRUD(Message)
