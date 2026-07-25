from uuid import UUID

from app.database.crud.base_crud import CRUDBase
from app.database.models import ConversableType, Conversation, Message, Paper
from app.schemas.user import CurrentUser
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session


class ConversationBase(BaseModel):
    conversable_type: ConversableType = ConversableType.PAPER
    conversable_id: UUID | None = None
    title: str | None = None


class ConversationCreate(ConversationBase):
    pass


class ConversationUpdate(BaseModel):
    title: str | None = None


class ConversationCRUD(CRUDBase[Conversation, ConversationCreate, ConversationUpdate]):
    """CRUD operations specifically for Conversation model"""

    def get_document_conversations(
        self, db: Session, *, paper_id: UUID, current_user: CurrentUser
    ) -> list[Conversation]:
        """Get all conversations for a document"""
        return list(
            db.scalars(
                select(Conversation)
                .where(
                    Conversation.conversable_id == paper_id,
                    Conversation.conversable_type == ConversableType.PAPER,
                    Conversation.user_id == current_user.id,
                )
                .order_by(Conversation.created_at)
            ).all()
        )

    def get_conversation_by_id(
        self, db: Session, *, conversation_id: UUID, user_id: int
    ) -> Conversation | None:
        """Get a conversation by its ID"""
        return db.scalars(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id
            )
        ).first()

    def get_by_share_paper_id(
        self, db: Session, *, share_paper_id: str
    ) -> Conversation | None:
        """Get a conversation by share paper ID"""
        paper = db.scalars(
            select(Paper).where(
                Paper.share_id == share_paper_id,
                Paper.is_public.is_(True),
            )
        ).first()

        if not paper:
            return None

        # Get the first conversation for that shared paper that has any associated `Message` objects
        return db.scalars(
            select(Conversation)
            .join(Message)
            .where(
                Conversation.conversable_id == paper.id,
                Conversation.conversable_type == ConversableType.PAPER,
            )
            .order_by(Conversation.created_at.desc())
        ).first()


# Create a single instance to use throughout the application
conversation_crud = ConversationCRUD(Conversation)
