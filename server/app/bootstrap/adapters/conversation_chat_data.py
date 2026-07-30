"""SQLAlchemy adapter for short, snapshot-based chat transactions."""

from __future__ import annotations

import uuid
from typing import cast

from app.bootstrap.adapters.conversation_access import conversation_policy
from app.bootstrap.adapters.conversation_repository import conversation_repository
from app.bootstrap.adapters.research_repository import research_repository
from app.database.models import Conversation
from app.database.models import Document, Project, ProjectPaper
from app.llm.token_credits import has_token_credits
from app.modules.conversations.application.chat import (
    ChatHistoryMessage,
    ChatPaperSnapshot,
    ChatProjectSnapshot,
    ConversationContextSnapshot,
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
from app.modules.papers.infrastructure.access import (
    accessible_document_condition,
    get_document_access,
)
from app.modules.papers.application.contracts.search import (
    LibraryPaperCollection,
    SelectedPaperCollection,
)
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind, JsonValue
from app.shared.domain.enums import ConversationScopeType
from sqlalchemy.orm import Session
from sqlalchemy import func, select


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
        paper_context = conversation_repository.paper_context(
            self._session,
            conversation=conversation,
            user_id=actor.id,
        )
        search_collection = (
            LibraryPaperCollection()
            if paper_context.kind == "library"
            else SelectedPaperCollection(
                project_ids=paper_context.project_ids,
                document_ids=paper_context.document_ids,
            )
        )
        return ConversationChatScope(
            scope_type=ConversationScopeType(conversation.scope_type),
            project_id=conversation.project_id,
            document_id=conversation.document_id,
            paper_context=search_collection,
        )

    def context(
        self,
        *,
        actor: Actor,
        scope: ConversationChatScope,
    ) -> ConversationContextSnapshot:
        context = scope.paper_context
        document_ids = (
            set(context.document_ids) if context.kind == "selection" else set()
        )
        if scope.document_id is not None:
            document_ids.add(scope.document_id)
        papers: list[ChatPaperSnapshot] = []
        for document_id in sorted(document_ids, key=str):
            paper = document_repository.find_accessible(
                self._session,
                document_id=document_id,
                user=actor,
            )
            if paper is None:
                continue
            papers.append(
                ChatPaperSnapshot(
                    document_id=paper.id,
                    title=paper.title,
                    abstract=paper.abstract if paper.id == scope.document_id else None,
                    raw_content=(
                        paper.raw_content if paper.id == scope.document_id else None
                    ),
                    keywords=paper.keywords,
                    authors=paper.authors,
                    publish_date=paper.publish_date,
                )
            )

        project_ids = context.project_ids if context.kind == "selection" else []
        project_rows = self._session.execute(
            select(
                Project.id,
                Project.title,
                Project.description,
                func.count(ProjectPaper.document_id),
            )
            .outerjoin(ProjectPaper, ProjectPaper.project_id == Project.id)
            .where(Project.id.in_(project_ids))
            .group_by(Project.id)
            .order_by(Project.id)
        ).all()
        projects = [
            ChatProjectSnapshot(
                project_id=project_id,
                title=title,
                description=description,
                document_count=int(document_count),
            )
            for project_id, title, description, document_count in project_rows
        ]
        available_document_count = (
            int(
                self._session.scalar(
                    select(func.count(Document.id)).where(
                        accessible_document_condition(user_id=actor.id)
                    )
                )
                or 0
            )
            if context.kind == "library"
            else None
        )
        return ConversationContextSnapshot(
            papers=papers,
            projects=projects,
            available_document_count=available_document_count,
        )

    def context_contains_document(
        self,
        *,
        actor: Actor,
        scope: ConversationChatScope,
        document_id: uuid.UUID,
    ) -> bool:
        if scope.document_id == document_id:
            return True
        context = scope.paper_context
        if context.kind == "library":
            return (
                get_document_access(
                    self._session,
                    document_id=document_id,
                    user_id=actor.id,
                )
                is not None
            )
        if document_id in context.document_ids:
            return True
        if not context.project_ids:
            return False
        return (
            self._session.scalar(
                select(ProjectPaper.document_id)
                .where(
                    ProjectPaper.document_id == document_id,
                    ProjectPaper.project_id.in_(context.project_ids),
                )
                .limit(1)
            )
            is not None
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

    def mentions(
        self,
        *,
        actor: Actor,
        request: ConversationMessageRequest,
    ) -> MentionScope:
        if not request.mentioned_highlight_ids:
            return MentionScope(None, None)

        snapshot: list[dict[str, JsonValue]] = []
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
