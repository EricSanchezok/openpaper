"""SQLAlchemy adapter for short, snapshot-based chat transactions."""

from __future__ import annotations

import uuid
from typing import Literal, cast

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
    PersistedChatResponse,
)
from app.modules.conversations.domain import DEFAULT_CONVERSATION_TITLE
from app.modules.conversations.application.contracts.turns import (
    ConversationTurnCreateRequest,
    ConversationTrace,
)
from app.modules.conversations.infrastructure.turn_repository import turn_repository
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
        history: list[ChatHistoryMessage] = []
        for turn in turn_repository.history(
            self._session,
            conversation_id=conversation_id,
            user_id=actor.id,
            exclude_turn_id=exclude_turn_id,
        ):
            selected = next(
                (
                    response
                    for response in turn.responses
                    if response.id == turn.selected_response_id
                ),
                None,
            )
            if selected is None or selected.content is None:
                continue
            history.append(ChatHistoryMessage(role="user", content=turn.user_query))
            history.append(
                ChatHistoryMessage(role="assistant", content=selected.content)
            )
        return history

    def mentions(
        self,
        *,
        actor: Actor,
        request: ConversationTurnCreateRequest,
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
    def _persisted(response: object) -> PersistedChatResponse:
        from app.modules.conversations.infrastructure.models import ConversationResponse

        if not isinstance(response, ConversationResponse):
            raise TypeError("expected ConversationResponse")
        return PersistedChatResponse(
            id=response.id,
            turn_id=response.turn_id,
            variant_index=response.variant_index,
            status=response.status,
            content=response.content or "",
            references=response.references,
            trace=(
                ConversationTrace.model_validate(response.trace)
                if response.trace is not None
                else None
            ),
        )

    def start_turn(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        turn_id: uuid.UUID,
        response_id: uuid.UUID,
        generation_kind: Literal["initial", "retry"],
        user_content: str,
        user_references: dict[str, JsonValue] | None,
        scope: list[dict[str, JsonValue]] | None,
        reasoning_level: str,
        locale: str,
        time_zone: str,
        created_operation_id: uuid.UUID,
        correlation_id: uuid.UUID,
    ) -> ConversationTurnStart:
        turn, turn_created = turn_repository.create_turn(
            self._session,
            conversation_id=conversation_id,
            turn_id=turn_id,
            user_id=actor.id,
            created_operation_id=created_operation_id,
            correlation_id=correlation_id,
            user_query=user_content,
            user_references=user_references,
            scope=scope,
            reasoning_level=reasoning_level,
            locale=locale,
            time_zone=time_zone,
        )
        response, response_created = turn_repository.create_response(
            self._session,
            conversation_id=conversation_id,
            turn_id=turn_id,
            response_id=response_id,
            user_id=actor.id,
            created_operation_id=created_operation_id,
            correlation_id=correlation_id,
            generation_kind=generation_kind,
        )
        return ConversationTurnStart(
            turn_id=turn.id,
            response=self._persisted(response),
            turn_operation_id=turn.created_operation_id,
            correlation_id=turn.correlation_id,
            turn_created=turn_created,
            response_created=response_created,
            generation_kind=generation_kind,
        )

    def complete_turn(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        turn_id: uuid.UUID,
        response_id: uuid.UUID,
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
        turn = turn_repository.require_turn(
            self._session,
            conversation_id=conversation_id,
            turn_id=turn_id,
            user_id=actor.id,
        )
        if turn.correlation_id != correlation_id:
            raise AppError(
                code="conversation_turn_causality_invalid",
                message="The conversation turn causality is invalid",
                kind=FailureKind.CONFLICT,
            )
        prior_status = next(
            (item.status for item in turn.responses if item.id == response_id),
            None,
        )
        response = turn_repository.complete_response(
            self._session,
            conversation_id=conversation_id,
            response_id=response_id,
            user_id=actor.id,
            content=assistant_content,
            references=assistant_references,
            trace=assistant_trace,
        )
        citation_ids: tuple[uuid.UUID, ...] = ()
        if artifacts and prior_status != "completed":
            citation_ids = tuple(
                item.id
                for item in research_repository.create_citations_for_response(
                    self._session,
                    conversation=conversation,
                    response_id=response.id,
                    user_id=actor.id,
                    snapshots=cast(list[dict[str, object]], artifacts),
                )
            )
        return ConversationTurnCompletion(
            response=self._persisted(response),
            created=prior_status != "completed",
            citation_ids=citation_ids,
        )

    def finish_response(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        response_id: uuid.UUID,
        status: str,
    ) -> None:
        turn_repository.finish_response(
            self._session,
            conversation_id=conversation_id,
            response_id=response_id,
            user_id=actor.id,
            status=status,
        )

    def retry_request(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        turn_id: uuid.UUID,
        response_id: uuid.UUID,
    ) -> ConversationTurnCreateRequest:
        turn = turn_repository.require_turn(
            self._session,
            conversation_id=conversation_id,
            turn_id=turn_id,
            user_id=actor.id,
        )
        if (
            turn_repository.latest_turn_id(
                self._session,
                conversation_id=conversation_id,
                user_id=actor.id,
            )
            != turn.id
        ):
            raise AppError(
                code="conversation_retry_not_latest",
                message="Only the latest turn can be retried",
                kind=FailureKind.CONFLICT,
            )
        raw_sources = (
            turn.user_references.get("sources")
            if isinstance(turn.user_references, dict)
            else None
        )
        sources = raw_sources if isinstance(raw_sources, list) else []
        user_references = [
            str(source["reference"])
            for source in sources
            if isinstance(source, dict) and source.get("reference") is not None
        ]
        mentioned_highlight_ids = [
            str(item["id"])
            for item in (turn.scope or [])
            if item.get("kind") == "highlight" and item.get("id") is not None
        ]
        return ConversationTurnCreateRequest.model_validate(
            {
                "turn_id": turn.id,
                "response_id": response_id,
                "user_query": turn.user_query,
                "locale": turn.locale,
                "time_zone": turn.time_zone,
                "user_references": user_references or None,
                "reasoning_level": turn.reasoning_level,
                "mentioned_highlight_ids": mentioned_highlight_ids or None,
            }
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
