"""SQLAlchemy adapter for short, snapshot-based chat transactions."""

from __future__ import annotations

import uuid
from typing import cast

from app.bootstrap.adapters.conversation_access import conversation_policy
from app.bootstrap.adapters.conversation_repository import conversation_repository
from app.bootstrap.adapters.project_documents import project_document_repository
from app.bootstrap.adapters.research_repository import research_repository
from app.database.models import Conversation
from app.llm.token_credits import has_token_credits
from app.modules.conversations.application.chat import (
    ChatHistoryMessage,
    ChatPaperSnapshot,
    ConversationChatDataGateway,
    ConversationChatScope,
    MentionScope,
)
from app.modules.conversations.application.contracts.conversations import (
    ConversationUpdateRequest,
)
from app.modules.conversations.application.contracts.messages import (
    ConversationMessageRequest,
)
from app.modules.conversations.infrastructure.message_repository import (
    MessageCreate,
    message_repository,
)
from app.modules.papers.infrastructure.repository import document_repository
from app.modules.projects.infrastructure.access import get_project_access
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind, JsonValue
from app.shared.domain.enums import ConversationScopeType
from sqlalchemy.orm import Session


class SqlAlchemyConversationChatData(ConversationChatDataGateway):
    def __init__(self, session: Session) -> None:
        self._session = session

    def prepare(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
    ) -> ConversationChatScope:
        if not has_token_credits(self._session, user=actor):
            raise AppError(
                code="token_quota_exceeded",
                message="Your weekly Token Credits are exhausted",
                kind=FailureKind.RATE_LIMITED,
            )
        conversation = self._conversation(actor=actor, conversation_id=conversation_id)
        conversation_policy.require_can_continue(
            self._session,
            conversation=conversation,
        )
        return ConversationChatScope(
            scope_type=ConversationScopeType(conversation.scope_type),
            project_id=conversation.project_id,
            document_id=conversation.document_id,
        )

    def history(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
    ) -> list[ChatHistoryMessage]:
        return [
            ChatHistoryMessage(role=message.role, content=message.content)
            for message in message_repository.get_conversation_messages(
                self._session,
                conversation_id=conversation_id,
                user_id=actor.id,
            )
        ]

    def papers(
        self,
        *,
        actor: Actor,
        project_id: uuid.UUID | None,
    ) -> list[ChatPaperSnapshot]:
        if project_id is None:
            papers = document_repository.list_available_library_documents(
                self._session,
                user=actor,
            )
        else:
            if (
                get_project_access(
                    self._session,
                    project_id=project_id,
                    user_id=actor.id,
                )
                is None
            ):
                return []
            papers = project_document_repository.get_all_papers_by_project_id(
                self._session,
                project_id=project_id,
                user=actor,
            )
        return [
            ChatPaperSnapshot(
                document_id=paper.id,
                title=paper.title,
                abstract=paper.abstract,
                raw_content=paper.raw_content,
                keywords=paper.keywords,
                authors=paper.authors,
                publish_date=paper.publish_date,
            )
            for paper in papers
        ]

    def mentions(
        self,
        *,
        actor: Actor,
        request: ConversationMessageRequest,
        project_id: uuid.UUID | None,
    ) -> MentionScope:
        if (
            not request.mentioned_document_ids
            and not request.mentioned_project_ids
            and not request.mentioned_highlight_ids
        ):
            return MentionScope(None, None, None)

        scoped: set[str] = set()
        snapshot: list[dict[str, JsonValue]] = []
        for document_id in request.mentioned_document_ids or []:
            if project_id is not None:
                paper = project_document_repository.get_paper_by_project(
                    self._session,
                    document_id=uuid.UUID(document_id),
                    project_id=project_id,
                    user=actor,
                )
            else:
                paper = document_repository.find_accessible(
                    self._session,
                    document_id=document_id,
                    user=actor,
                )
            if paper is not None:
                scoped.add(str(paper.id))
                snapshot.append(
                    {
                        "kind": "paper",
                        "id": str(paper.id),
                        "title": paper.title,
                    }
                )

        for mentioned_project_id in request.mentioned_project_ids or []:
            project_access = get_project_access(
                self._session,
                project_id=uuid.UUID(mentioned_project_id),
                user_id=actor.id,
            )
            if project_access is None:
                continue
            document_ids = (
                project_document_repository.get_project_document_ids_by_project_id(
                    self._session,
                    project_id=uuid.UUID(mentioned_project_id),
                    user=actor,
                )
            )
            scoped.update(str(document_id) for document_id in document_ids)
            snapshot.append(
                {
                    "kind": "project",
                    "id": str(project_access.project.id),
                    "title": project_access.project.title,
                }
            )

        highlights_by_paper: dict[str, dict[str, JsonValue]] = {}
        for highlight_id in request.mentioned_highlight_ids or []:
            try:
                item = research_repository.get_highlight_thread_visible(
                    self._session,
                    thread_id=uuid.UUID(highlight_id),
                    user_id=actor.id,
                )
            except AppError:
                continue
            highlight = item.highlight_thread
            if highlight is None or item.document_id is None:
                continue
            document_id = str(item.document_id)
            scoped.add(document_id)
            group = highlights_by_paper.get(document_id)
            if group is None:
                paper = document_repository.find_accessible(
                    self._session,
                    document_id=document_id,
                    user=actor,
                )
                group = {
                    "document_id": document_id,
                    "paper_title": paper.title if paper else None,
                    "paper_abstract": paper.abstract if paper else None,
                    "highlights": [],
                }
                highlights_by_paper[document_id] = group
            annotations = [
                comment.content for comment in highlight.comments if comment.content
            ]
            json_annotations = cast(list[JsonValue], annotations)
            snapshot.append(
                {
                    "kind": "highlight",
                    "id": str(item.id),
                    "title": highlight.quote_text,
                    "document_id": document_id,
                    "paper_title": group["paper_title"],
                    "annotations": json_annotations,
                }
            )
            highlights = group["highlights"]
            assert isinstance(highlights, list)
            highlights.append(
                {
                    "highlighted_text": highlight.quote_text,
                    "page_number": highlight.page_number,
                    "annotations": json_annotations,
                }
            )
        return MentionScope(
            document_ids=list(scoped),
            snapshot=snapshot,
            highlights=list(highlights_by_paper.values()),
        )

    def save_turn(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        user_content: str,
        user_references: dict[str, JsonValue] | None,
        scope: list[dict[str, JsonValue]] | None,
        assistant_content: str,
        assistant_references: dict[str, JsonValue] | None,
        assistant_trace: dict[str, JsonValue] | None,
        artifacts: list[dict[str, JsonValue]],
    ) -> None:
        conversation = self._conversation(
            actor=actor,
            conversation_id=conversation_id,
        )
        message_repository.create(
            self._session,
            request=MessageCreate(
                conversation_id=conversation_id,
                role="user",
                content=user_content,
                references=user_references,
                scope=scope,
            ),
            user_id=actor.id,
        )
        assistant_message = message_repository.create(
            self._session,
            request=MessageCreate(
                conversation_id=conversation_id,
                role="assistant",
                content=assistant_content,
                references=assistant_references,
                trace=assistant_trace,
            ),
            user_id=actor.id,
        )
        if artifacts:
            research_repository.create_citations_for_message(
                self._session,
                conversation=conversation,
                message_id=assistant_message.id,
                user_id=actor.id,
                snapshots=cast(list[dict[str, object]], artifacts),
            )

    def rename(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        title: str,
    ) -> None:
        conversation_repository.update(
            self._session,
            conversation_id=conversation_id,
            user_id=actor.id,
            request=ConversationUpdateRequest(title=title),
        )

    def _conversation(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
    ) -> Conversation:
        return conversation_repository.require_owned(
            self._session,
            conversation_id=conversation_id,
            user_id=actor.id,
        )
