import logging
import uuid
from collections.abc import Sequence

from app.modules.conversations.infrastructure.message_repository import (
    message_repository,
)
from app.database.database import get_db
from app.llm.base import BaseLLMClient
from app.llm.prompts import (
    NAME_DATA_TABLE_SYSTEM_PROMPT,
    NAME_DATA_TABLE_USER_MESSAGE,
    RENAME_CONVERSATION_SYSTEM_PROMPT,
    RENAME_CONVERSATION_USER_MESSAGE,
)
from app.llm.backend import TextContent
from app.llm.backend import HistoryMessage
from app.bootstrap.adapters.conversation_repository import conversation_repository
from app.modules.conversations.application.contracts.conversations import (
    ConversationUpdateRequest,
)
from app.shared.application import Actor
from fastapi import Depends
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class ConversationOperations(BaseLLMClient):
    """Operations related to conversations"""

    def rename_conversation(
        self,
        conversation_id: str,
        user: Actor,
        db: Session = Depends(get_db),
    ) -> str | None:
        """
        Rename a conversation based on its chat history
        """
        casted_uuid = uuid.UUID(conversation_id)
        conversation = conversation_repository.require_owned(
            db, conversation_id=casted_uuid, user_id=user.id
        )

        chat_history = message_repository.get_conversation_messages(
            db, conversation_id=casted_uuid, user_id=user.id
        )

        new_title = self.generate_title(chat_history)
        if new_title is None:
            logger.warning(
                f"Conversation with ID {conversation_id} has no messages. Cannot rename."
            )
            return None
        conversation_repository.update(
            db,
            conversation_id=conversation.id,
            user_id=user.id,
            request=ConversationUpdateRequest(title=new_title),
        )
        return new_title

    def generate_title(
        self,
        chat_history: Sequence[HistoryMessage],
    ) -> str | None:
        if not chat_history:
            return None
        # Format the chat history for the LLM, restrict to the last 4 messages
        formatted_chat_history = "\n".join(
            [f"{msg.role}: {msg.content}" for msg in chat_history[-4:]]
        )

        formatted_prompt = RENAME_CONVERSATION_USER_MESSAGE.format(
            chat_history=formatted_chat_history
        )

        message_content = [
            TextContent(text=formatted_prompt),
        ]

        # Generate a new title using the LLM
        response = self.generate_content(
            contents=message_content,
            system_prompt=RENAME_CONVERSATION_SYSTEM_PROMPT,
        )

        if response and response.text:
            return response.text.strip()
        logger.error("Failed to generate a new conversation title.")
        return None


class DataTableOperations(BaseLLMClient):
    """Operations related to data tables"""

    def name_data_table(
        self,
        paper_titles: list[str],
        column_labels: list[str],
    ) -> str | None:
        """
        Generate a concise title for a data table based on paper titles and column labels.

        Args:
            paper_titles: List of paper titles included in the data table
            column_labels: List of column labels in the data table

        Returns:
            A title of 10 words or less, or None if generation fails
        """
        formatted_papers = "\n".join([f"- {title}" for title in paper_titles])
        formatted_columns = ", ".join(column_labels)

        formatted_prompt = NAME_DATA_TABLE_USER_MESSAGE.format(
            paper_titles=formatted_papers,
            column_labels=formatted_columns,
        )

        message_content = [
            TextContent(text=formatted_prompt),
        ]

        response = self.generate_content(
            contents=message_content,
            system_prompt=NAME_DATA_TABLE_SYSTEM_PROMPT,
        )

        if response and response.text:
            return response.text.strip()
        else:
            logger.error("Failed to generate a title for the data table.")
            return None


conversation_operations = ConversationOperations()
data_table_operations = DataTableOperations()
