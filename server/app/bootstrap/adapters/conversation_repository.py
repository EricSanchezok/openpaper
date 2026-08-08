"""Typed persistence for user-owned conversations."""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.database.models import (
    Conversation,
    ConversationContextDocument,
    ConversationContextProject,
    ConversationScopeType,
)
from app.shared.domain import AppError, FailureKind
from app.bootstrap.adapters.conversation_access import conversation_policy
from app.modules.papers.infrastructure.access import get_document_access
from app.modules.projects.infrastructure.access import get_project_access
from app.modules.conversations.application.contracts.conversations import (
    ConversationCapabilitiesResponse,
    ConversationCreateRequest,
    ConversationMoveRequest,
    LibraryPaperContext,
    PaperContext,
    SelectedPaperContext,
    ConversationSummaryResponse,
    ConversationUpdateRequest,
    ConversationToolPermissionsRequest,
    ConversationToolPermissionsResponse,
)
from app.modules.conversations.domain import DEFAULT_CONVERSATION_TITLE
from app.shared.domain import (
    WorkspacePermission,
    ordered_workspace_permissions,
)
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class ConversationWrite[T]:
    value: T
    changed: bool


def _not_found() -> AppError:
    return AppError(
        code="conversation_not_found",
        message="Conversation not found",
        kind=FailureKind.NOT_FOUND,
    )


def _encode_cursor(conversation: Conversation) -> str:
    payload = json.dumps(
        {
            "p": (
                conversation.pinned_at.isoformat() if conversation.pinned_at else None
            ),
            "u": conversation.updated_at.isoformat(),
            "i": str(conversation.id),
        },
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime | None, datetime, uuid.UUID]:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding).decode())
        pinned_at = datetime.fromisoformat(payload["p"]) if payload["p"] else None
        return pinned_at, datetime.fromisoformat(payload["u"]), uuid.UUID(payload["i"])
    except (
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
    ) as exc:
        raise AppError(
            code="conversation_cursor_invalid",
            message="Conversation cursor is invalid",
            kind=FailureKind.UNPROCESSABLE,
        ) from exc


class ConversationRepository:
    @staticmethod
    def tool_permissions(
        conversation: Conversation,
    ) -> list[WorkspacePermission]:
        return ordered_workspace_permissions(conversation.tool_permissions)

    def paper_context(
        self,
        db: Session,
        *,
        conversation: Conversation,
        user_id: int,
    ) -> PaperContext:
        if conversation.paper_context_kind == "library":
            return LibraryPaperContext()

        project_ids = set(
            db.scalars(
                select(ConversationContextProject.project_id).where(
                    ConversationContextProject.conversation_id == conversation.id
                )
            ).all()
        )
        document_ids = set(
            db.scalars(
                select(ConversationContextDocument.document_id).where(
                    ConversationContextDocument.conversation_id == conversation.id
                )
            ).all()
        )
        if conversation.project_id is not None:
            project_ids.add(conversation.project_id)
        if conversation.document_id is not None:
            document_ids.add(conversation.document_id)

        accessible_projects = {
            project_id
            for project_id in project_ids
            if get_project_access(db, project_id=project_id, user_id=user_id)
            is not None
        }
        accessible_documents = {
            document_id
            for document_id in document_ids
            if get_document_access(db, document_id=document_id, user_id=user_id)
            is not None
        }
        return SelectedPaperContext(
            kind="selection",
            project_ids=sorted(accessible_projects, key=str),
            document_ids=sorted(accessible_documents, key=str),
        )

    def _replace_paper_context(
        self,
        db: Session,
        *,
        conversation: Conversation,
        user_id: int,
        request: PaperContext,
    ) -> ConversationWrite[PaperContext]:
        current_project_ids = set(
            db.scalars(
                select(ConversationContextProject.project_id).where(
                    ConversationContextProject.conversation_id == conversation.id
                )
            ).all()
        )
        current_document_ids = set(
            db.scalars(
                select(ConversationContextDocument.document_id).where(
                    ConversationContextDocument.conversation_id == conversation.id
                )
            ).all()
        )

        if isinstance(request, LibraryPaperContext):
            context_kind = "library"
            project_ids: set[uuid.UUID] = set()
            document_ids: set[uuid.UUID] = set()
        else:
            context_kind = "selection"
            project_ids = set(request.project_ids)
            document_ids = set(request.document_ids)
            if conversation.project_id is not None:
                project_ids.discard(conversation.project_id)
            if conversation.document_id is not None:
                document_ids.discard(conversation.document_id)
            if (
                conversation.project_id is None
                and conversation.document_id is None
                and not project_ids
                and not document_ids
            ):
                raise AppError(
                    code="conversation_context_empty",
                    message="A selected paper context cannot be empty",
                    kind=FailureKind.UNPROCESSABLE,
                )
            for project_id in project_ids:
                if (
                    get_project_access(db, project_id=project_id, user_id=user_id)
                    is None
                ):
                    raise AppError(
                        code="conversation_context_project_not_found",
                        message="A selected project was not found",
                        kind=FailureKind.NOT_FOUND,
                    )
            for document_id in document_ids:
                if (
                    get_document_access(
                        db,
                        document_id=document_id,
                        user_id=user_id,
                    )
                    is None
                ):
                    raise AppError(
                        code="conversation_context_document_not_found",
                        message="A selected paper was not found",
                        kind=FailureKind.NOT_FOUND,
                    )

        changed = (
            conversation.paper_context_kind != context_kind
            or current_project_ids != project_ids
            or current_document_ids != document_ids
        )
        if not changed:
            return ConversationWrite(
                value=self.paper_context(
                    db,
                    conversation=conversation,
                    user_id=user_id,
                ),
                changed=False,
            )

        db.execute(
            delete(ConversationContextProject).where(
                ConversationContextProject.conversation_id == conversation.id
            )
        )
        db.execute(
            delete(ConversationContextDocument).where(
                ConversationContextDocument.conversation_id == conversation.id
            )
        )
        conversation.paper_context_kind = context_kind
        db.add_all(
            ConversationContextProject(
                conversation_id=conversation.id,
                project_id=project_id,
            )
            for project_id in sorted(project_ids, key=str)
        )
        db.add_all(
            ConversationContextDocument(
                conversation_id=conversation.id,
                document_id=document_id,
            )
            for document_id in sorted(document_ids, key=str)
        )
        db.flush()
        return ConversationWrite(
            value=self.paper_context(
                db,
                conversation=conversation,
                user_id=user_id,
            ),
            changed=True,
        )

    def update_paper_context(
        self,
        db: Session,
        *,
        conversation_id: uuid.UUID,
        user_id: int,
        request: PaperContext,
    ) -> ConversationWrite[PaperContext]:
        conversation = self.require_owned(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            for_update=True,
        )
        conversation_policy.require_can_continue(db, conversation=conversation)
        return self._replace_paper_context(
            db,
            conversation=conversation,
            user_id=user_id,
            request=request,
        )

    def update_tool_permissions(
        self,
        db: Session,
        *,
        conversation_id: uuid.UUID,
        user_id: int,
        request: ConversationToolPermissionsRequest,
    ) -> ConversationWrite[ConversationToolPermissionsResponse]:
        conversation = self.require_owned(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            for_update=True,
        )
        permissions = ordered_workspace_permissions(request.permissions)
        response = ConversationToolPermissionsResponse(permissions=permissions)
        normalized = [permission.value for permission in permissions]
        if conversation.tool_permissions == normalized:
            return ConversationWrite(value=response, changed=False)
        conversation.tool_permissions = normalized
        db.flush()
        return ConversationWrite(value=response, changed=True)

    def require_owned(
        self,
        db: Session,
        *,
        conversation_id: uuid.UUID,
        user_id: int,
        for_update: bool = False,
    ) -> Conversation:
        statement = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
        if for_update:
            statement = statement.with_for_update()
        conversation = db.scalar(statement)
        if conversation is None:
            raise _not_found()
        return conversation

    def summarize(
        self,
        db: Session,
        *,
        conversation: Conversation,
    ) -> ConversationSummaryResponse:
        access = conversation_policy.evaluate(db, conversation=conversation)
        scope_type = ConversationScopeType(conversation.scope_type)
        scope_id = (
            conversation.project_id
            if scope_type == ConversationScopeType.PROJECT
            else conversation.document_id
            if scope_type == ConversationScopeType.PAPER
            else None
        )
        return ConversationSummaryResponse(
            id=conversation.id,
            title=conversation.title,
            updated_at=conversation.updated_at,
            scope_type=scope_type,
            scope_id=scope_id,
            scope_label=access.scope_label,
            scope_access="active" if access.can_continue else "lost",
            read_only=not access.can_continue,
            read_only_reason=access.read_only_reason,
            pinned_at=conversation.pinned_at,
            archived_at=conversation.archived_at,
            capabilities=ConversationCapabilitiesResponse(
                move=(
                    scope_type != ConversationScopeType.PAPER and access.can_continue
                ),
                detach=(
                    scope_type == ConversationScopeType.PROJECT and access.can_continue
                ),
                send=access.can_continue,
            ),
        )

    def create(
        self,
        db: Session,
        *,
        request: ConversationCreateRequest,
        user_id: int,
        refresh_result: bool = True,
    ) -> Conversation:
        project_id: uuid.UUID | None = None
        document_id: uuid.UUID | None = None
        scope_label: str | None = None
        if request.scope_type == ConversationScopeType.PROJECT:
            assert request.scope_id is not None
            access = get_project_access(
                db,
                project_id=request.scope_id,
                user_id=user_id,
            )
            if access is None:
                raise AppError(
                    code="project_not_found",
                    message="Project not found",
                    kind=FailureKind.NOT_FOUND,
                )
            project_id = request.scope_id
            scope_label = access.project.title
        elif request.scope_type == ConversationScopeType.PAPER:
            assert request.scope_id is not None
            document_access = get_document_access(
                db,
                document_id=request.scope_id,
                user_id=user_id,
            )
            if document_access is None:
                raise AppError(
                    code="paper_not_found",
                    message="Paper not found",
                    kind=FailureKind.NOT_FOUND,
                )
            document_id = request.scope_id
            scope_label = document_access.document.title

        requested_permissions = request.tool_permissions
        if requested_permissions is None:
            requested_permissions = [
                WorkspacePermission.READ,
                WorkspacePermission.WRITE,
            ]
        conversation = Conversation(
            title=request.title or DEFAULT_CONVERSATION_TITLE,
            user_id=user_id,
            scope_type=request.scope_type.value,
            project_id=project_id,
            document_id=document_id,
            scope_label_snapshot=scope_label,
            paper_context_kind=(
                "library"
                if request.scope_type == ConversationScopeType.GLOBAL
                else "selection"
            ),
            tool_permissions=[
                permission.value
                for permission in ordered_workspace_permissions(requested_permissions)
            ],
        )
        db.add(conversation)
        db.flush()
        if request.paper_context is not None:
            self._replace_paper_context(
                db,
                conversation=conversation,
                user_id=user_id,
                request=request.paper_context,
            )
        if refresh_result:
            db.flush()
            db.refresh(conversation)
        else:
            db.flush()
        return conversation

    def list(
        self,
        db: Session,
        *,
        user_id: int,
        archived: bool,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Conversation], str | None]:
        statement = select(Conversation).where(
            Conversation.user_id == user_id,
            (
                Conversation.archived_at.isnot(None)
                if archived
                else Conversation.archived_at.is_(None)
            ),
        )
        if cursor:
            pinned_at, updated_at, conversation_id = _decode_cursor(cursor)
            if pinned_at is not None:
                statement = statement.where(
                    or_(
                        Conversation.pinned_at.is_(None),
                        Conversation.pinned_at < pinned_at,
                        and_(
                            Conversation.pinned_at == pinned_at,
                            or_(
                                Conversation.updated_at < updated_at,
                                and_(
                                    Conversation.updated_at == updated_at,
                                    Conversation.id < conversation_id,
                                ),
                            ),
                        ),
                    )
                )
            else:
                statement = statement.where(
                    Conversation.pinned_at.is_(None),
                    or_(
                        Conversation.updated_at < updated_at,
                        and_(
                            Conversation.updated_at == updated_at,
                            Conversation.id < conversation_id,
                        ),
                    ),
                )
        conversations = list(
            db.scalars(
                statement.order_by(
                    Conversation.pinned_at.desc().nulls_last(),
                    Conversation.updated_at.desc(),
                    Conversation.id.desc(),
                ).limit(limit + 1)
            ).all()
        )
        has_more = len(conversations) > limit
        conversations = conversations[:limit]
        return conversations, (
            _encode_cursor(conversations[-1]) if has_more and conversations else None
        )

    def update(
        self,
        db: Session,
        *,
        conversation_id: uuid.UUID,
        user_id: int,
        request: ConversationUpdateRequest,
    ) -> ConversationWrite[Conversation]:
        conversation = self.require_owned(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            for_update=True,
        )
        desired_title = (
            request.title if request.title is not None else conversation.title
        )
        desired_pinned_at = conversation.pinned_at
        desired_archived_at = conversation.archived_at
        now: datetime | None = None
        if request.pinned is not None:
            if request.pinned and desired_pinned_at is None:
                now = datetime.now(timezone.utc)
                desired_pinned_at = now
            elif not request.pinned:
                desired_pinned_at = None
        if request.archived is not None:
            if request.archived and desired_archived_at is None:
                now = now or datetime.now(timezone.utc)
                desired_archived_at = now
            elif not request.archived:
                desired_archived_at = None
            if request.archived:
                desired_pinned_at = None
        changed = (
            desired_title != conversation.title
            or desired_pinned_at != conversation.pinned_at
            or desired_archived_at != conversation.archived_at
        )
        if not changed:
            return ConversationWrite(value=conversation, changed=False)
        conversation.title = desired_title
        conversation.pinned_at = desired_pinned_at
        conversation.archived_at = desired_archived_at
        db.flush()
        db.refresh(conversation)
        return ConversationWrite(value=conversation, changed=True)

    def apply_initial_generated_title(
        self,
        db: Session,
        *,
        conversation_id: uuid.UUID,
        user_id: int,
        title: str,
    ) -> bool:
        """Apply the first generated title without overwriting a user rename."""
        conversation = self.require_owned(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            for_update=True,
        )
        if conversation.title != DEFAULT_CONVERSATION_TITLE:
            return False
        conversation.title = title
        db.flush()
        return True

    def move(
        self,
        db: Session,
        *,
        conversation_id: uuid.UUID,
        user_id: int,
        request: ConversationMoveRequest,
    ) -> ConversationWrite[Conversation]:
        conversation = self.require_owned(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            for_update=True,
        )
        conversation_policy.require_can_continue(db, conversation=conversation)
        if conversation.scope_type == ConversationScopeType.PAPER.value:
            raise AppError(
                code="paper_conversation_scope_fixed",
                message="Paper conversations cannot change scope",
                kind=FailureKind.CONFLICT,
            )

        if request.scope_type == ConversationScopeType.PROJECT.value:
            assert request.scope_id is not None
            if (
                conversation.scope_type == ConversationScopeType.PROJECT.value
                and conversation.project_id == request.scope_id
            ):
                return ConversationWrite(value=conversation, changed=False)
            access = get_project_access(
                db,
                project_id=request.scope_id,
                user_id=user_id,
            )
            if access is None:
                raise AppError(
                    code="project_not_found",
                    message="Project not found",
                    kind=FailureKind.NOT_FOUND,
                )
            conversation.scope_type = ConversationScopeType.PROJECT.value
            conversation.project_id = request.scope_id
            conversation.document_id = None
            conversation.scope_label_snapshot = access.project.title
            default_context: PaperContext = SelectedPaperContext()
        else:
            if conversation.scope_type == ConversationScopeType.GLOBAL.value:
                return ConversationWrite(value=conversation, changed=False)
            conversation.scope_type = ConversationScopeType.GLOBAL.value
            conversation.project_id = None
            conversation.document_id = None
            conversation.scope_label_snapshot = None
            default_context = LibraryPaperContext()
        self._replace_paper_context(
            db,
            conversation=conversation,
            user_id=user_id,
            request=default_context,
        )
        db.flush()
        db.refresh(conversation)
        return ConversationWrite(value=conversation, changed=True)

    def delete(
        self,
        db: Session,
        *,
        conversation_id: uuid.UUID,
        user_id: int,
    ) -> None:
        conversation = self.require_owned(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            for_update=True,
        )
        db.delete(conversation)
        db.flush()


conversation_repository = ConversationRepository()
