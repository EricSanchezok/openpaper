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
    ConversationTurnCompletion,
    ConversationTurnStart,
    MentionScope,
    PersistedChatMessage,
)
from app.modules.conversations.domain import DEFAULT_CONVERSATION_TITLE
from app.modules.conversations.application.contracts.messages import (
    ConversationMessageRequest,
    ConversationTrace,
)
from app.modules.conversations.infrastructure.message_repository import (
    MessageCreate,
    message_repository,
)
from app.modules.papers.infrastructure.repository import document_repository
from app.modules.papers.infrastructure.access import accessible_document_condition
from app.modules.papers.application.contracts.search import (
    LibraryPaperCollection,
    SelectedPaperCollection,
)
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind, JsonValue
from app.shared.domain import normalize_workspace_permissions
from app.shared.domain.enums import ConversationScopeType
from app.shared.domain.enums import RoleType
from app.helpers.postgres import sanitize_for_postgres
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
            tool_permissions=normalize_workspace_permissions(
                conversation.tool_permissions
            ),
            title_is_default=conversation.title == DEFAULT_CONVERSATION_TITLE,
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

    def history(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        exclude_turn_id: uuid.UUID | None,
    ) -> list[ChatHistoryMessage]:
        return [
            ChatHistoryMessage(role=message.role, content=message.content)
            for message in message_repository.get_conversation_messages(
                self._session,
                conversation_id=conversation_id,
                user_id=actor.id,
                exclude_turn_id=exclude_turn_id,
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

    @staticmethod
    def _persisted(message: object) -> PersistedChatMessage:
        from app.modules.conversations.infrastructure.models import Message

        if not isinstance(message, Message):
            raise TypeError("expected Message")
        return PersistedChatMessage(
            id=message.id,
            turn_id=message.turn_id,
            content=message.content,
            references=message.references,
            trace=(
                ConversationTrace.model_validate(message.trace)
                if message.trace is not None
                else None
            ),
        )

    def start_turn(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        turn_id: uuid.UUID,
        user_content: str,
        user_references: dict[str, JsonValue] | None,
        scope: list[dict[str, JsonValue]] | None,
        created_operation_id: uuid.UUID,
        correlation_id: uuid.UUID,
    ) -> ConversationTurnStart:
        message_repository.lock_conversation(
            self._session,
            conversation_id=conversation_id,
            user_id=actor.id,
        )
        existing_user = message_repository.find_turn_message(
            self._session,
            conversation_id=conversation_id,
            user_id=actor.id,
            turn_id=turn_id,
            role=RoleType.USER,
        )
        if existing_user is not None:
            normalized_content = sanitize_for_postgres(user_content)
            if existing_user.content != normalized_content:
                raise AppError(
                    code="conversation_turn_conflict",
                    message="This conversation turn was already used differently",
                    kind=FailureKind.CONFLICT,
                )
            existing_assistant = message_repository.find_turn_message(
                self._session,
                conversation_id=conversation_id,
                user_id=actor.id,
                turn_id=turn_id,
                role=RoleType.ASSISTANT,
            )
            return ConversationTurnStart(
                user_message_id=existing_user.id,
                user_operation_id=existing_user.created_operation_id,
                correlation_id=existing_user.correlation_id,
                created=False,
                assistant=(
                    self._persisted(existing_assistant)
                    if existing_assistant is not None
                    else None
                ),
            )

        user_message = message_repository.create(
            self._session,
            request=MessageCreate(
                conversation_id=conversation_id,
                turn_id=turn_id,
                created_operation_id=created_operation_id,
                correlation_id=correlation_id,
                role=RoleType.USER,
                content=user_content,
                references=user_references,
                scope=scope,
            ),
            user_id=actor.id,
        )
        return ConversationTurnStart(
            user_message_id=user_message.id,
            user_operation_id=user_message.created_operation_id,
            correlation_id=user_message.correlation_id,
            created=True,
            assistant=None,
        )

    def complete_turn(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        turn_id: uuid.UUID,
        assistant_content: str,
        assistant_references: dict[str, JsonValue] | None,
        assistant_trace: ConversationTrace | None,
        artifacts: list[dict[str, JsonValue]],
        created_operation_id: uuid.UUID,
        correlation_id: uuid.UUID,
    ) -> ConversationTurnCompletion:
        conversation = self._conversation(
            actor=actor,
            conversation_id=conversation_id,
        )
        message_repository.lock_conversation(
            self._session,
            conversation_id=conversation_id,
            user_id=actor.id,
        )
        existing = message_repository.find_turn_message(
            self._session,
            conversation_id=conversation_id,
            user_id=actor.id,
            turn_id=turn_id,
            role=RoleType.ASSISTANT,
        )
        if existing is not None:
            return ConversationTurnCompletion(
                assistant=self._persisted(existing),
                created=False,
                citation_ids=(),
            )
        user_message = message_repository.find_turn_message(
            self._session,
            conversation_id=conversation_id,
            user_id=actor.id,
            turn_id=turn_id,
            role=RoleType.USER,
        )
        if user_message is None:
            raise AppError(
                code="conversation_turn_not_started",
                message="The conversation turn has not been started",
                kind=FailureKind.CONFLICT,
            )
        if user_message.correlation_id != correlation_id:
            raise AppError(
                code="conversation_turn_causality_invalid",
                message="The conversation turn causality is invalid",
                kind=FailureKind.CONFLICT,
            )
        assistant_message = message_repository.create(
            self._session,
            request=MessageCreate(
                conversation_id=conversation_id,
                turn_id=turn_id,
                created_operation_id=created_operation_id,
                correlation_id=correlation_id,
                role=RoleType.ASSISTANT,
                content=assistant_content,
                references=assistant_references,
                trace=assistant_trace,
            ),
            user_id=actor.id,
        )
        citation_ids: tuple[uuid.UUID, ...] = ()
        if artifacts:
            citation_ids = tuple(
                item.id
                for item in research_repository.create_citations_for_message(
                    self._session,
                    conversation=conversation,
                    message_id=assistant_message.id,
                    user_id=actor.id,
                    snapshots=cast(list[dict[str, object]], artifacts),
                )
            )
        return ConversationTurnCompletion(
            assistant=self._persisted(assistant_message),
            created=True,
            citation_ids=citation_ids,
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
