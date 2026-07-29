"""Explicit persistence and visibility queries for typed research items."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.database.models import (
    AnnotationComment,
    CitationOutput,
    HighlightThread,
    ResearchItem,
    ResearchItemKind,
    ResearchScopeType,
    RoleType,
    Conversation,
    ConversationScopeType,
)
from app.shared.infrastructure.persistence import JsonValue
from app.errors import AppError
from app.helpers.s3 import s3_service
from app.policies.documents import require_document_access
from app.policies.research import research_item_policy, research_item_visible_to
from app.schemas.research import (
    AnnotationCommentResponse,
    AudioOverviewContent,
    CitationContent,
    CitationSnapshot,
    DataTableContent,
    HighlightThreadContent,
    ResearchCreatorResponse,
    ResearchItemCapabilities,
    ResearchItemResponse,
)
from pydantic import TypeAdapter
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

_CITATION_SNAPSHOTS = TypeAdapter(list[CitationSnapshot])


@dataclass(frozen=True, slots=True)
class HighlightThreadCreate:
    quote_text: str
    page_number: int | None
    start_offset: int | None
    end_offset: int | None
    position: dict[str, JsonValue] | None
    color: str
    is_shared: bool
    role: str = RoleType.USER.value
    zotero_annotation_key: str | None = None


class ResearchRepository:
    def require_visible(
        self,
        db: Session,
        *,
        item_id: uuid.UUID,
        user_id: int,
        for_update: bool = False,
    ) -> ResearchItem:
        statement = select(ResearchItem).where(
            ResearchItem.id == item_id,
            research_item_visible_to(user_id),
        )
        if for_update:
            statement = statement.with_for_update()
        item = db.scalar(statement)
        if item is None:
            raise AppError(
                code="research_item_not_found",
                message="Research item not found",
                status_code=404,
            )
        research_item_policy.require_visible(db, item=item, user_id=user_id)
        return item

    def require_creator_owned(
        self,
        db: Session,
        *,
        item_id: uuid.UUID,
        user_id: int,
        for_update: bool = False,
    ) -> ResearchItem:
        item = self.require_visible(
            db,
            item_id=item_id,
            user_id=user_id,
            for_update=for_update,
        )
        research_item_policy.require_creator_manager(
            db,
            item=item,
            user_id=user_id,
        )
        return item

    def list_for_document(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
        kind: ResearchItemKind | None = None,
    ) -> list[ResearchItem]:
        require_document_access(db, document_id=document_id, user_id=user_id)
        statement = (
            select(ResearchItem)
            .where(
                ResearchItem.scope_type == ResearchScopeType.DOCUMENT.value,
                ResearchItem.document_id == document_id,
                or_(
                    ResearchItem.is_shared.is_(True),
                    ResearchItem.created_by_id == user_id,
                ),
            )
            .order_by(ResearchItem.created_at.asc(), ResearchItem.id.asc())
            .options(
                joinedload(ResearchItem.created_by),
                joinedload(ResearchItem.citation),
                joinedload(ResearchItem.audio_overview),
                joinedload(ResearchItem.data_table),
                joinedload(ResearchItem.highlight_thread)
                .selectinload(HighlightThread.comments)
                .joinedload(AnnotationComment.created_by),
            )
        )
        if kind is not None:
            statement = statement.where(ResearchItem.kind == kind.value)
        return list(db.scalars(statement).unique().all())

    def list_for_project(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        user_id: int,
    ) -> list[ResearchItem]:
        from app.policies.projects import require_project_access

        require_project_access(db, project_id=project_id, user_id=user_id)
        return list(
            db.scalars(
                select(ResearchItem)
                .where(
                    ResearchItem.scope_type == ResearchScopeType.PROJECT.value,
                    ResearchItem.project_id == project_id,
                    or_(
                        ResearchItem.is_shared.is_(True),
                        ResearchItem.created_by_id == user_id,
                    ),
                )
                .order_by(ResearchItem.created_at.desc(), ResearchItem.id.desc())
                .options(
                    joinedload(ResearchItem.created_by),
                    joinedload(ResearchItem.citation),
                    joinedload(ResearchItem.audio_overview),
                    joinedload(ResearchItem.data_table),
                )
            )
            .unique()
            .all()
        )

    def create_highlight_thread(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
        create: HighlightThreadCreate,
        auto_commit: bool = True,
    ) -> ResearchItem:
        require_document_access(db, document_id=document_id, user_id=user_id)
        item = ResearchItem(
            kind=ResearchItemKind.HIGHLIGHT_THREAD.value,
            created_by_id=user_id,
            scope_type=ResearchScopeType.DOCUMENT.value,
            document_id=document_id,
            is_shared=create.is_shared,
        )
        item.highlight_thread = HighlightThread(
            quote_text=create.quote_text,
            page_number=create.page_number,
            start_offset=create.start_offset,
            end_offset=create.end_offset,
            position=create.position,
            color=create.color,
            role=create.role,
            zotero_annotation_key=create.zotero_annotation_key,
        )
        db.add(item)
        if auto_commit:
            db.commit()
            db.refresh(item)
        else:
            db.flush()
        return item

    def has_assistant_highlight(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
    ) -> bool:
        return (
            db.scalar(
                select(ResearchItem.id)
                .join(
                    HighlightThread,
                    HighlightThread.research_item_id == ResearchItem.id,
                )
                .where(
                    ResearchItem.document_id == document_id,
                    HighlightThread.role == RoleType.ASSISTANT.value,
                )
                .limit(1)
            )
            is not None
        )

    def create_citation(
        self,
        db: Session,
        *,
        user_id: int,
        snapshot: CitationSnapshot,
        source_message_id: uuid.UUID,
        scope_type: ResearchScopeType,
        scope_id: uuid.UUID | None,
    ) -> ResearchItem:
        item = ResearchItem(
            kind=ResearchItemKind.CITATION.value,
            created_by_id=user_id,
            scope_type=scope_type.value,
            document_id=(
                scope_id if scope_type == ResearchScopeType.DOCUMENT else None
            ),
            project_id=(scope_id if scope_type == ResearchScopeType.PROJECT else None),
            is_shared=scope_type != ResearchScopeType.PERSONAL,
            source_message_id=source_message_id,
        )
        item.citation = CitationOutput(snapshot=snapshot.model_dump(mode="json"))
        db.add(item)
        return item

    def create_citations_for_message(
        self,
        db: Session,
        *,
        conversation: Conversation,
        message_id: uuid.UUID,
        user_id: int,
        snapshots: list[dict[str, object]],
    ) -> list[ResearchItem]:
        scope_type = ConversationScopeType(conversation.scope_type)
        if scope_type == ConversationScopeType.GLOBAL:
            research_scope = ResearchScopeType.PERSONAL
            scope_id = None
        elif scope_type == ConversationScopeType.PROJECT:
            research_scope = ResearchScopeType.PROJECT
            scope_id = conversation.project_id
        else:
            research_scope = ResearchScopeType.DOCUMENT
            scope_id = conversation.document_id
        validated_snapshots = _CITATION_SNAPSHOTS.validate_python(snapshots)
        items = [
            self.create_citation(
                db,
                user_id=user_id,
                snapshot=snapshot,
                source_message_id=message_id,
                scope_type=research_scope,
                scope_id=scope_id,
            )
            for snapshot in validated_snapshots
        ]
        db.commit()
        return items

    def get_highlight_thread_visible(
        self,
        db: Session,
        *,
        thread_id: uuid.UUID,
        user_id: int,
    ) -> ResearchItem:
        item = db.scalar(
            select(ResearchItem)
            .where(
                ResearchItem.id == thread_id,
                ResearchItem.kind == ResearchItemKind.HIGHLIGHT_THREAD.value,
                research_item_visible_to(user_id),
            )
            .options(
                joinedload(ResearchItem.highlight_thread)
                .selectinload(HighlightThread.comments)
                .joinedload(AnnotationComment.created_by),
                joinedload(ResearchItem.created_by),
            )
        )
        if item is None:
            raise AppError(
                code="highlight_thread_not_found",
                message="Highlight thread not found",
                status_code=404,
            )
        research_item_policy.require_visible(db, item=item, user_id=user_id)
        return item

    def get_zotero_annotation_keys(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
    ) -> set[str]:
        return {
            key
            for key in db.scalars(
                select(HighlightThread.zotero_annotation_key)
                .join(
                    ResearchItem,
                    ResearchItem.id == HighlightThread.research_item_id,
                )
                .where(
                    ResearchItem.document_id == document_id,
                    ResearchItem.created_by_id == user_id,
                    HighlightThread.zotero_annotation_key.isnot(None),
                )
            ).all()
            if key is not None
        }

    def find_zotero_backfill_candidate(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
        quote_text: str,
        page_number: int | None,
    ) -> HighlightThread | None:
        return db.scalar(
            select(HighlightThread)
            .join(
                ResearchItem,
                ResearchItem.id == HighlightThread.research_item_id,
            )
            .where(
                ResearchItem.document_id == document_id,
                ResearchItem.created_by_id == user_id,
                HighlightThread.zotero_annotation_key.is_(None),
                HighlightThread.quote_text == quote_text,
                HighlightThread.page_number.is_not_distinct_from(page_number),
            )
            .order_by(ResearchItem.created_at.asc())
            .limit(1)
        )

    @staticmethod
    def set_zotero_annotation_key(
        db: Session,
        *,
        thread: HighlightThread,
        zotero_annotation_key: str,
    ) -> None:
        thread.zotero_annotation_key = zotero_annotation_key
        db.commit()

    def add_comment(
        self,
        db: Session,
        *,
        thread_id: uuid.UUID,
        user_id: int,
        content: str,
        role: str = RoleType.USER.value,
        auto_commit: bool = True,
    ) -> AnnotationComment:
        item = self.require_visible(db, item_id=thread_id, user_id=user_id)
        if item.kind != ResearchItemKind.HIGHLIGHT_THREAD.value:
            raise AppError(
                code="highlight_thread_not_found",
                message="Highlight thread not found",
                status_code=404,
            )
        access = research_item_policy.evaluate(db, item=item, user_id=user_id)
        if not access.has_scope_access:
            raise AppError(
                code="research_item_scope_access_lost",
                message="This thread is read-only until scope access is restored",
                status_code=409,
            )
        comment = AnnotationComment(
            thread_id=thread_id,
            created_by_id=user_id,
            content=content,
            role=role,
        )
        db.add(comment)
        if auto_commit:
            db.commit()
            db.refresh(comment)
        else:
            db.flush()
        return comment

    def require_owned_comment(
        self,
        db: Session,
        *,
        comment_id: uuid.UUID,
        user_id: int,
        for_update: bool = False,
    ) -> AnnotationComment:
        statement = (
            select(AnnotationComment)
            .join(
                ResearchItem,
                ResearchItem.id == AnnotationComment.thread_id,
            )
            .where(
                AnnotationComment.id == comment_id,
                AnnotationComment.created_by_id == user_id,
            )
        )
        if for_update:
            statement = statement.with_for_update()
        comment = db.scalar(statement)
        if comment is None:
            raise AppError(
                code="annotation_comment_not_found",
                message="Annotation comment not found",
                status_code=404,
            )
        item = db.get(ResearchItem, comment.thread_id)
        if item is None:
            raise RuntimeError("annotation_comment_without_research_item")
        access = research_item_policy.evaluate(db, item=item, user_id=user_id)
        if not access.has_scope_access:
            raise AppError(
                code="research_item_scope_access_lost",
                message="This comment is read-only until scope access is restored",
                status_code=409,
            )
        return comment

    def set_visibility(
        self,
        db: Session,
        *,
        item_id: uuid.UUID,
        user_id: int,
        shared: bool,
    ) -> ResearchItem:
        item = self.require_creator_owned(
            db,
            item_id=item_id,
            user_id=user_id,
            for_update=True,
        )
        if item.scope_type == ResearchScopeType.PERSONAL.value and shared:
            raise AppError(
                code="personal_research_cannot_be_shared",
                message="Personal research cannot be shared without a target scope",
                status_code=409,
            )
        item.is_shared = shared
        db.commit()
        db.refresh(item)
        return item

    def update_highlight_thread(
        self,
        db: Session,
        *,
        thread_id: uuid.UUID,
        user_id: int,
        values: dict[str, object],
    ) -> ResearchItem:
        item = self.require_creator_owned(
            db,
            item_id=thread_id,
            user_id=user_id,
            for_update=True,
        )
        if (
            item.kind != ResearchItemKind.HIGHLIGHT_THREAD.value
            or item.highlight_thread is None
        ):
            raise AppError(
                code="highlight_thread_not_found",
                message="Highlight thread not found",
                status_code=404,
            )
        shared = values.pop("shared", None)
        if shared is not None:
            item.is_shared = bool(shared)
        for field, value in values.items():
            setattr(item.highlight_thread, field, value)
        db.commit()
        db.refresh(item)
        return item

    def update_comment(
        self,
        db: Session,
        *,
        comment_id: uuid.UUID,
        user_id: int,
        content: str,
    ) -> AnnotationComment:
        comment = self.require_owned_comment(
            db,
            comment_id=comment_id,
            user_id=user_id,
            for_update=True,
        )
        comment.content = content
        db.commit()
        db.refresh(comment)
        return comment

    def delete_comment(
        self,
        db: Session,
        *,
        comment_id: uuid.UUID,
        user_id: int,
    ) -> None:
        comment = self.require_owned_comment(
            db,
            comment_id=comment_id,
            user_id=user_id,
            for_update=True,
        )
        db.delete(comment)
        db.commit()

    def delete_item(
        self,
        db: Session,
        *,
        item_id: uuid.UUID,
        user_id: int,
        confirm_delete_replies: bool = False,
    ) -> None:
        item = self.require_creator_owned(
            db,
            item_id=item_id,
            user_id=user_id,
            for_update=True,
        )
        if item.kind == ResearchItemKind.HIGHLIGHT_THREAD.value:
            other_reply_count = int(
                db.scalar(
                    select(func.count(AnnotationComment.id)).where(
                        AnnotationComment.thread_id == item.id,
                        AnnotationComment.created_by_id.is_distinct_from(user_id),
                    )
                )
                or 0
            )
            if other_reply_count and not confirm_delete_replies:
                raise AppError(
                    code="highlight_thread_has_other_replies",
                    message="Confirm deletion of replies from other contributors",
                    status_code=409,
                    details={"affected_reply_count": other_reply_count},
                )
        object_key = (
            item.audio_overview.s3_object_key
            if item.audio_overview is not None
            else None
        )
        db.delete(item)
        db.flush()
        if object_key is not None:
            from app.services.storage_cleanup import schedule_storage_deletion

            schedule_storage_deletion(
                db,
                object_keys=[object_key],
                idempotency_key=f"research-item:{item.id}",
            )
        db.commit()

    def serialize(
        self,
        db: Session,
        *,
        item: ResearchItem,
        user_id: int,
    ) -> ResearchItemResponse:
        access = research_item_policy.require_visible(
            db,
            item=item,
            user_id=user_id,
        )
        creator = ResearchCreatorResponse(
            id=item.created_by_id,
            display_name=(
                item.created_by.display_name if item.created_by is not None else None
            ),
        )
        scope_type = ResearchScopeType(item.scope_type)
        scope_id = (
            item.document_id
            if scope_type == ResearchScopeType.DOCUMENT
            else item.project_id
            if scope_type == ResearchScopeType.PROJECT
            else None
        )
        highlight: HighlightThreadContent | None = None
        citation: CitationContent | None = None
        audio: AudioOverviewContent | None = None
        data_table: DataTableContent | None = None
        if item.highlight_thread is not None:
            highlight = HighlightThreadContent(
                quote_text=item.highlight_thread.quote_text,
                page_number=item.highlight_thread.page_number,
                start_offset=item.highlight_thread.start_offset,
                end_offset=item.highlight_thread.end_offset,
                position=item.highlight_thread.position,
                color=item.highlight_thread.color,
                role=item.highlight_thread.role,
                comments=[
                    self.serialize_comment(
                        comment,
                        user_id=user_id,
                        has_scope_access=access.has_scope_access,
                    )
                    for comment in item.highlight_thread.comments
                ],
            )
        elif item.citation is not None:
            citation = CitationContent(
                snapshot=CitationSnapshot.model_validate(item.citation.snapshot)
            )
        elif item.audio_overview is not None:
            audio = AudioOverviewContent.model_validate(
                {
                    "title": item.audio_overview.title,
                    "transcript": item.audio_overview.transcript,
                    "citations": item.audio_overview.citations,
                    "audio_url": s3_service.generate_presigned_url(
                        item.audio_overview.s3_object_key
                    ),
                    "voice_id": item.audio_overview.voice_id,
                    "model_version": item.audio_overview.model_version,
                }
            )
        elif item.data_table is not None:
            data_table = DataTableContent(
                title=item.data_table.title,
                columns=item.data_table.columns,
                rows=item.data_table.rows,
                citations=item.data_table.citations,
                row_failures=item.data_table.row_failures,
            )
        return ResearchItemResponse(
            id=item.id,
            kind=ResearchItemKind(item.kind),
            scope_type=scope_type,
            scope_id=scope_id,
            is_shared=item.is_shared,
            created_by=creator,
            created_at=item.created_at,
            updated_at=item.updated_at,
            capabilities=ResearchItemCapabilities(
                share=access.can_manage,
                edit=access.can_manage,
                delete=access.can_manage,
            ),
            highlight_thread=highlight,
            citation=citation,
            audio_overview=audio,
            data_table=data_table,
        )

    @staticmethod
    def serialize_comment(
        comment: AnnotationComment,
        *,
        user_id: int,
        has_scope_access: bool,
    ) -> AnnotationCommentResponse:
        can_manage = comment.created_by_id == user_id and has_scope_access
        return AnnotationCommentResponse(
            id=comment.id,
            thread_id=comment.thread_id,
            content=comment.content,
            role=comment.role,
            created_by=ResearchCreatorResponse(
                id=comment.created_by_id,
                display_name=(
                    comment.created_by.display_name
                    if comment.created_by is not None
                    else None
                ),
            ),
            created_at=comment.created_at,
            updated_at=comment.updated_at,
            can_edit=can_manage,
            can_delete=can_manage,
        )


research_repository = ResearchRepository()
