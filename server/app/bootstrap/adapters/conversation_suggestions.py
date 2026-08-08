"""SQLAlchemy persistence adapter for response follow-up suggestions."""

from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from app.modules.conversations.application.contracts.answer_packet import (
    ReferenceBundle,
)
from app.modules.conversations.application.suggestions import (
    SuggestionClaim,
    SuggestionSeed,
    SuggestionStatus,
)
from app.modules.conversations.infrastructure.turn_repository import turn_repository
from app.shared.domain import AppError, FailureKind
from sqlalchemy.orm import Session

_MAX_SOURCE_TITLES = 12
_MAX_SOURCE_TITLE_CHARS = 200


def _verified_source_titles(references: object) -> tuple[str, ...]:
    if references is None:
        return ()
    bundle = ReferenceBundle.model_validate(references)
    titles: list[str] = []
    seen: set[str] = set()
    for source in bundle.sources:
        title = getattr(source, "title", None)
        if not isinstance(title, str):
            continue
        normalized = " ".join(title.split()).strip()[:_MAX_SOURCE_TITLE_CHARS]
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        titles.append(normalized)
        if len(titles) == _MAX_SOURCE_TITLES:
            break
    return tuple(titles)


class SqlAlchemyConversationSuggestionGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def claim(
        self, *, user_id: int, conversation_id: UUID, response_id: UUID
    ) -> SuggestionClaim:
        turn_repository.lock_conversation(
            self._db, conversation_id=conversation_id, user_id=user_id
        )
        response = turn_repository.require_response(
            self._db,
            conversation_id=conversation_id,
            response_id=response_id,
            user_id=user_id,
            lock=True,
        )
        latest_turn_id = turn_repository.latest_turn_id(
            self._db, conversation_id=conversation_id, user_id=user_id
        )
        if (
            response.turn_id != latest_turn_id
            or response.turn.selected_response_id != response.id
        ):
            raise AppError(
                code="conversation_suggestions_not_latest",
                message="Suggestions are only available for the latest selected response",
                kind=FailureKind.CONFLICT,
            )
        if response.status != "completed" or response.content is None:
            raise AppError(
                code="conversation_suggestions_response_incomplete",
                message="Suggestions require a completed response",
                kind=FailureKind.CONFLICT,
            )
        status = response.suggestions_status
        if status in {"pending", "completed", "failed"}:
            return SuggestionClaim(
                response_id=response.id,
                status=cast(SuggestionStatus, status),
                suggestions=tuple(response.suggestions or ()),
            )
        response.suggestions_status = "pending"
        response.suggestions = None
        self._db.flush()
        return SuggestionClaim(
            response_id=response.id,
            status="pending",
            seed=SuggestionSeed(
                response_id=response.id,
                user_query=response.turn.user_query,
                final_answer=response.content,
                locale=cast(Literal["en", "zh-CN"], response.turn.locale),
                source_titles=_verified_source_titles(response.references),
            ),
        )

    def complete(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        response_id: UUID,
        suggestions: tuple[str, str, str],
    ) -> SuggestionClaim:
        turn_repository.lock_conversation(
            self._db, conversation_id=conversation_id, user_id=user_id
        )
        response = turn_repository.require_response(
            self._db,
            conversation_id=conversation_id,
            response_id=response_id,
            user_id=user_id,
            lock=True,
        )
        latest_turn_id = turn_repository.latest_turn_id(
            self._db, conversation_id=conversation_id, user_id=user_id
        )
        if (
            response.turn_id != latest_turn_id
            or response.turn.selected_response_id != response.id
        ):
            return SuggestionClaim(response_id=response.id, status="failed")
        if response.suggestions_status == "completed":
            return SuggestionClaim(
                response_id=response.id,
                status="completed",
                suggestions=tuple(response.suggestions or ()),
            )
        if response.suggestions_status != "pending":
            raise AppError(
                code="conversation_suggestions_not_pending",
                message="Suggestion generation is not pending",
                kind=FailureKind.CONFLICT,
            )
        response.suggestions = list(suggestions)
        response.suggestions_status = "completed"
        self._db.flush()
        return SuggestionClaim(
            response_id=response.id,
            status="completed",
            suggestions=suggestions,
        )

    def fail(
        self, *, user_id: int, conversation_id: UUID, response_id: UUID
    ) -> SuggestionClaim:
        turn_repository.lock_conversation(
            self._db, conversation_id=conversation_id, user_id=user_id
        )
        response = turn_repository.require_response(
            self._db,
            conversation_id=conversation_id,
            response_id=response_id,
            user_id=user_id,
            lock=True,
        )
        latest_turn_id = turn_repository.latest_turn_id(
            self._db, conversation_id=conversation_id, user_id=user_id
        )
        if (
            response.turn_id != latest_turn_id
            or response.turn.selected_response_id != response.id
        ):
            return SuggestionClaim(response_id=response.id, status="failed")
        if response.suggestions_status == "pending":
            response.suggestions = None
            response.suggestions_status = "failed"
            self._db.flush()
        return SuggestionClaim(
            response_id=response.id,
            status=cast(SuggestionStatus, response.suggestions_status),
            suggestions=tuple(response.suggestions or ()),
        )
