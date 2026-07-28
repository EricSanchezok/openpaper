import hashlib
import logging
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import TypedDict

from app.database.crud.annotation_crud import AnnotationCreate, annotation_crud
from app.database.crud.base_crud import CRUDBase
from app.database.crud.highlight_crud import HighlightCreate, highlight_crud
from app.database.crud.paper_image_crud import paper_image_crud
from app.database.crud.sanitization import sanitize_for_postgres
from app.database.models import (
    AuthUser,
    Document,
    DocumentProcessingStatus,
    Highlight,
    JsonValue,
    LibraryPaper,
    PaperImage,
    PaperStatus,
    PaperTag,
    PaperUploadJob,
    Project,
    ProjectPaper,
    RoleType,
)
from app.helpers.paper_search import normalize_doi
from app.helpers.parser import get_start_page_from_offset
from app.llm.utils import find_offsets
from app.policies.documents import (
    get_document_access,
    get_library_paper,
)
from app.schemas.responses import PaperMetadataExtraction, ResponseCitation
from app.schemas.user import CurrentUser
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, load_only, selectinload

logger = logging.getLogger(__name__)


class PassageInsert(TypedDict):
    start_line: int
    end_line: int
    content: str


# Define Pydantic models for type safety
class PaperBase(BaseModel):
    sha256: str | None = None
    original_filename: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    s3_object_key: str | None = None
    preview_s3_key: str | None = None
    authors: list[str] | None = None
    title: str | None = None
    abstract: str | None = None
    institutions: list[str] | None = None
    keywords: list[str] | None = None
    summary: str | None = None
    summary_citations: list[ResponseCitation] | None = None
    starter_questions: list[str] | None = None
    publish_date: str | None = None
    raw_content: str | None = None
    parser_markdown_s3_key: str | None = None
    parser_archive_s3_key: str | None = None
    parser_backend: str | None = None
    parser_quality: str | None = None
    parser_version: str | None = None
    parser_warning_code: str | None = None
    processing_status: str | None = None
    processing_job_id: uuid.UUID | None = None
    gc_after: datetime | None = None
    # We can't save tuples in the db, so we use a list (length 2) to represent page offsets
    page_offset_map: dict[int, list[int]] | None = None


class PaperCreate(PaperBase):
    sha256: str
    original_filename: str
    mime_type: str = "application/pdf"
    size_bytes: int
    s3_object_key: str


class PaperUpdate(PaperBase):
    status: PaperStatus | None = None
    raw_content: str | None = None
    doi: str | None = None
    journal: str | None = None
    publisher: str | None = None
    attempted_metadata_at: datetime | None = None
    field_provenance: dict[str, JsonValue] | None = None


class PaperDocumentMetadata(BaseModel):
    raw_content: str | None = None
    page_offsets: dict[int, tuple[int, int]] | None = None


# Document CRUD that inherits from the base CRUD
class PaperCRUD(CRUDBase["Document", PaperCreate, PaperUpdate]):
    """Persistence boundary for canonical documents and personal library entries."""

    def create(
        self,
        db: Session,
        *,
        obj_in: PaperCreate,
        user: CurrentUser | None = None,
        add_to_library: bool = True,
        auto_commit: bool = True,
    ) -> Document:
        if user is None:
            raise ValueError("user is required when creating a document")
        data = sanitize_for_postgres(obj_in.model_dump())
        document = Document(
            **data,
            created_by_id=user.id,
        )
        db.add(document)
        db.flush()
        if add_to_library:
            db.add(
                LibraryPaper(
                    user_id=user.id,
                    document_id=document.id,
                    status=PaperStatus.reading,
                )
            )
        if auto_commit:
            db.commit()
        else:
            db.flush()
        db.refresh(document)
        return document

    def get(
        self,
        db: Session,
        id: object,
        *,
        user: CurrentUser | None = None,
        update_last_accessed: bool = False,
    ) -> Document | None:
        try:
            document_id = uuid.UUID(str(id))
        except (TypeError, ValueError):
            return None
        if user is None:
            return db.get(Document, document_id)
        access = get_document_access(
            db,
            document_id=document_id,
            user_id=user.id,
        )
        if access is None:
            return None
        if update_last_accessed and access.library_paper is not None:
            access.library_paper.last_accessed_at = datetime.now(timezone.utc)
            db.commit()
        return access.document

    def update(
        self,
        db: Session,
        *,
        db_obj: Document,
        obj_in: PaperUpdate | dict[str, object],
        user: CurrentUser | None = None,
    ) -> Document | None:
        if user is not None:
            access = get_document_access(
                db,
                document_id=db_obj.id,
                user_id=user.id,
            )
            if access is None:
                return None
        else:
            access = None
        update_data = (
            obj_in
            if isinstance(obj_in, dict)
            else obj_in.model_dump(exclude_unset=True)
        )
        status = update_data.pop("status", None)
        if status is not None:
            library_paper = (
                access.library_paper
                if access is not None
                else (
                    get_library_paper(
                        db,
                        document_id=db_obj.id,
                        user_id=user.id,
                    )
                    if user is not None
                    else None
                )
            )
            if library_paper is None:
                return None
            library_paper.status = (
                status.value if isinstance(status, PaperStatus) else str(status)
            )
        sanitized = sanitize_for_postgres(update_data)
        for field, value in sanitized.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def remove(
        self,
        db: Session,
        *,
        id: object,
        user: CurrentUser | None = None,
    ) -> Document | None:
        if user is None:
            raise ValueError("user is required when removing a library paper")
        try:
            document_id = uuid.UUID(str(id))
        except (TypeError, ValueError):
            return None
        library_paper = get_library_paper(
            db,
            document_id=document_id,
            user_id=user.id,
        )
        if library_paper is None:
            return None
        document = db.get(Document, document_id)
        db.delete(library_paper)
        db.flush()
        from app.services.document_gc import schedule_document_gc

        schedule_document_gc(db, document_id=document_id)
        db.commit()
        return document

    def schedule_orphan_document_gc(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        gc_after: datetime,
    ) -> bool:
        """Schedule cleanup only when the canonical document has no references."""
        document = db.scalar(
            select(Document).where(Document.id == document_id).with_for_update()
        )
        if document is None:
            return False
        reference_count = int(
            db.scalar(
                select(func.count(LibraryPaper.id) + func.count(ProjectPaper.id))
                .select_from(Document)
                .outerjoin(
                    LibraryPaper,
                    LibraryPaper.document_id == Document.id,
                )
                .outerjoin(
                    ProjectPaper,
                    ProjectPaper.document_id == Document.id,
                )
                .where(Document.id == document_id)
            )
            or 0
        )
        if reference_count:
            return False
        document.gc_after = gc_after
        db.commit()
        return True

    def get_library_paper(
        self, db: Session, *, document_id: uuid.UUID, user: CurrentUser
    ) -> LibraryPaper | None:
        return get_library_paper(
            db,
            document_id=document_id,
            user_id=user.id,
        )

    def get_library_papers(
        self,
        db: Session,
        *,
        document_ids: list[uuid.UUID],
        user: CurrentUser,
    ) -> dict[uuid.UUID, LibraryPaper]:
        if not document_ids:
            return {}
        entries = db.scalars(
            select(LibraryPaper).where(
                LibraryPaper.user_id == user.id,
                LibraryPaper.document_id.in_(document_ids),
            )
        ).all()
        return {entry.document_id: entry for entry in entries}

    def read_raw_document_content(
        self,
        db: Session,
        *,
        paper_id: str,
        current_user: CurrentUser,
    ) -> PaperDocumentMetadata:
        """
        Read raw document content by ID.
        For PDF files, extract and return the text content.
        """
        paper: Document | None = self.get(db, paper_id, user=current_user)
        if paper is None:
            raise ValueError(f"Paper with ID {paper_id} not found.")

        if not paper.raw_content:
            raise ValueError(f"Raw content for paper {paper_id} is not set.")

        offsets = (
            {k: (v[0], v[1]) for k, v in paper.page_offset_map.items() if len(v) >= 2}
            if paper.page_offset_map
            else {}
        )

        return PaperDocumentMetadata(
            raw_content=str(paper.raw_content),
            page_offsets=offsets,
        )

    def get_top_relevant_papers(
        self, db: Session, *, user: CurrentUser, limit: int = 3
    ) -> list[Document]:
        """
        Get recent papers with priority logic:
        1. Order by most recently uploaded
        2. First get papers with 'reading' status
        3. If under limit, fill with 'todo' status papers
        4. Return up to limit papers
        """
        # First, get reading papers
        reading_papers = db.scalars(
            select(Document)
            .join(LibraryPaper, LibraryPaper.document_id == Document.id)
            .where(
                LibraryPaper.user_id == user.id,
                LibraryPaper.status == PaperStatus.reading,
            )
            .where(Document.processing_status == DocumentProcessingStatus.COMPLETED)
            .order_by(LibraryPaper.last_accessed_at.desc())
            .limit(limit)
        ).all()

        # If we have enough reading papers, return them
        if len(reading_papers) >= limit:
            return list(reading_papers)

        # Calculate how many more papers we need
        remaining_limit = limit - len(reading_papers)

        # Get todo papers to fill the remaining slots
        todo_papers = db.scalars(
            select(Document)
            .join(LibraryPaper, LibraryPaper.document_id == Document.id)
            .where(
                LibraryPaper.user_id == user.id,
                LibraryPaper.status == PaperStatus.todo,
            )
            .order_by(LibraryPaper.last_accessed_at.desc())
            .limit(remaining_limit)
        ).all()

        # Combine and return
        return list(reading_papers) + list(todo_papers)

    def get_size_of_knowledge_base(self, db: Session, *, user: CurrentUser) -> int:
        """Return logical reference storage billed to the account in KB."""
        library_bytes = int(
            db.scalar(
                select(func.coalesce(func.sum(Document.size_bytes), 0))
                .join(LibraryPaper, LibraryPaper.document_id == Document.id)
                .where(
                    LibraryPaper.user_id == user.id,
                    Document.processing_status == DocumentProcessingStatus.COMPLETED,
                )
            )
            or 0
        )
        project_bytes = int(
            db.scalar(
                select(func.coalesce(func.sum(Document.size_bytes), 0))
                .join(ProjectPaper, ProjectPaper.document_id == Document.id)
                .join(Project, Project.id == ProjectPaper.project_id)
                .where(
                    Project.owner_id == user.id,
                    Document.processing_status == DocumentProcessingStatus.COMPLETED,
                )
            )
            or 0
        )
        return (library_bytes + project_bytes + 1023) // 1024

    def has_unknown_billed_document_size(
        self,
        db: Session,
        *,
        user_id: int,
    ) -> bool:
        """Canonical documents always persist exact byte size."""
        return False

    def make_public(
        self, db: Session, *, paper_id: str, user: CurrentUser
    ) -> tuple[Document, str] | None:
        """Create a rotating public share token and persist only its hash."""
        paper = self.get(db, id=paper_id, user=user)
        if paper:
            library_paper = get_library_paper(
                db,
                document_id=paper.id,
                user_id=user.id,
            )
            if library_paper is None:
                return None
            token = secrets.token_urlsafe(32)
            library_paper.share_token_hash = hashlib.sha256(token.encode()).hexdigest()
            library_paper.is_public = True
            db.commit()
            return paper, token
        return None

    def make_private(
        self, db: Session, *, paper_id: str, user: CurrentUser
    ) -> Document | None:
        """Make a paper private (not publicly accessible)"""
        paper = self.get(db, id=paper_id, user=user)
        if paper:
            library_paper = get_library_paper(
                db,
                document_id=paper.id,
                user_id=user.id,
            )
            if library_paper is None:
                return None
            library_paper.is_public = False
            library_paper.share_token_hash = None
            db.commit()
        return paper

    def get_public_paper(self, db: Session, *, share_id: str) -> Document | None:
        """Resolve a raw public token without persisting it."""
        token_hash = hashlib.sha256(share_id.encode()).hexdigest()
        return db.scalar(
            select(Document)
            .join(LibraryPaper, LibraryPaper.document_id == Document.id)
            .where(
                LibraryPaper.share_token_hash == token_hash,
                LibraryPaper.is_public.is_(True),
            )
        )

    def get_public_library_paper(
        self, db: Session, *, share_id: str
    ) -> LibraryPaper | None:
        token_hash = hashlib.sha256(share_id.encode()).hexdigest()
        return db.scalar(
            select(LibraryPaper).where(
                LibraryPaper.share_token_hash == token_hash,
                LibraryPaper.is_public.is_(True),
            )
        )

    def get_by_upload_job_id(
        self, db: Session, *, upload_job_id: str, user: CurrentUser
    ) -> Document | None:
        """Get the document created by one of the user's upload jobs."""
        return db.scalar(
            select(Document)
            .join(PaperUploadJob, PaperUploadJob.document_id == Document.id)
            .where(
                PaperUploadJob.id == upload_job_id,
                PaperUploadJob.user_id == user.id,
            )
        )

    def get_total_paper_count(self, db: Session, *, user: CurrentUser) -> int:
        """Count every completed logical Library and owned-Project reference."""
        library_count = int(
            db.scalar(
                select(func.count(LibraryPaper.id))
                .join(Document, Document.id == LibraryPaper.document_id)
                .where(
                    LibraryPaper.user_id == user.id,
                    Document.processing_status == DocumentProcessingStatus.COMPLETED,
                )
            )
            or 0
        )
        project_count = int(
            db.scalar(
                select(func.count(ProjectPaper.id))
                .join(Document, Document.id == ProjectPaper.document_id)
                .join(Project, Project.id == ProjectPaper.project_id)
                .where(
                    Project.owner_id == user.id,
                    Document.processing_status == DocumentProcessingStatus.COMPLETED,
                )
            )
            or 0
        )
        return library_count + project_count

    def get_multi_uploads_completed(
        self,
        db: Session,
        *,
        user: CurrentUser,
        skip: int = 0,
        limit: int = 500,
        status: PaperStatus | None = None,
    ) -> list[Document]:
        """
        Get completed canonical documents referenced by the user's Library.
        """
        statement = (
            select(Document)
            .options(
                load_only(
                    Document.title,
                    Document.created_at,
                    Document.updated_at,
                    Document.abstract,
                    Document.authors,
                    Document.institutions,
                    Document.preview_s3_key,
                    Document.size_bytes,
                    Document.publish_date,
                ),
            )
            .join(LibraryPaper, LibraryPaper.document_id == Document.id)
            .where(
                LibraryPaper.user_id == user.id,
                Document.processing_status == DocumentProcessingStatus.COMPLETED,
            )
            .order_by(LibraryPaper.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        if status:
            statement = statement.where(LibraryPaper.status == status)
        return list(db.scalars(statement).all())

    def get_tags_by_document_ids(
        self,
        db: Session,
        *,
        document_ids: list[uuid.UUID],
        user: CurrentUser,
    ) -> dict[uuid.UUID, list[PaperTag]]:
        if not document_ids:
            return {}
        entries = db.scalars(
            select(LibraryPaper)
            .options(selectinload(LibraryPaper.tags))
            .where(
                LibraryPaper.user_id == user.id,
                LibraryPaper.document_id.in_(document_ids),
            )
        ).all()
        return {entry.document_id: list(entry.tags) for entry in entries}

    def create_ai_annotations(
        self,
        db: Session,
        *,
        paper_id: str,
        extract_metadata: PaperMetadataExtraction,
        current_user: CurrentUser,
    ) -> None:
        # Idempotency: a redelivered upload job (Celery acks_late) can invoke this
        # twice for the same paper. If AI highlights already exist, this has
        # already run — skip to avoid duplicating highlights and annotations.
        existing_ai_highlight = db.scalars(
            select(Highlight).where(
                Highlight.paper_id == uuid.UUID(paper_id),
                Highlight.role == RoleType.ASSISTANT,
            )
        ).first()
        if existing_ai_highlight:
            logger.info(
                f"AI highlights already exist for paper {paper_id}, "
                f"skipping AI annotation creation"
            )
            return

        raw_file = self.read_raw_document_content(
            db, paper_id=paper_id, current_user=current_user
        )

        if not raw_file.raw_content:
            raise ValueError(f"Raw content for paper {paper_id} is not set.")

        for ai_highlight in extract_metadata.highlights:
            offsets = find_offsets(ai_highlight.text, raw_file.raw_content)

            page_number = None
            if offsets and raw_file.page_offsets:
                # Get the starting page number from the offsets
                page_number = get_start_page_from_offset(
                    raw_file.page_offsets, offsets[0]
                )

            new_ai_highlight_obj = HighlightCreate(
                paper_id=uuid.UUID(paper_id),
                raw_text=ai_highlight.text,
                type=ai_highlight.type,
                start_offset=offsets[0],
                end_offset=offsets[1],
                page_number=page_number,
                role=RoleType.ASSISTANT,
            )

            n_ai_h = highlight_crud.create(
                db, obj_in=new_ai_highlight_obj, user=current_user
            )

            if not n_ai_h:
                logger.error(
                    f"Failed to create AI highlights for {paper_id}",
                    exc_info=True,
                )
                continue

            n_annotation_obj = AnnotationCreate(
                paper_id=uuid.UUID(paper_id),
                highlight_id=n_ai_h.id,
                role=RoleType.ASSISTANT,
                content=ai_highlight.annotation,
            )

            n_ai_annotation = annotation_crud.create(
                db, obj_in=n_annotation_obj, user=current_user
            )

            if not n_ai_annotation:
                logger.error(
                    f"Failed to create AI annotation for highlight {n_ai_h.id} in {paper_id}",
                    exc_info=True,
                )

    def get_summary_replace_image_placeholders(
        self, db: Session, *, paper_id: str, current_user: CurrentUser
    ) -> str:
        """Replace image placeholders with actual images in the paper.

        Args:
            db (Session): Database session.
            paper_id (str): ID of the paper to update.
            user (CurrentUser): Current user making the request.
        """

        def _find_and_replace_all_placeholders(
            summary: str, images: list[PaperImage]
        ) -> str:
            """Find all the image placeholders in the paper. Placeholders are referenced by markdown-style image syntax, where the link is just the placeholder ID. If a placeholder is found, replace it with the actual image URL."""
            for image in images:
                placeholder = f"({image.placeholder_id})"
                from app.helpers.s3 import s3_service

                image_url = s3_service.generate_presigned_url(image.s3_object_key)
                summary = summary.replace(placeholder, f"({image_url})")

            # Remove any remaining image references in markdown format that don't match database entries
            # Match markdown image syntax: ![alt text](url) or ![](url)
            # Split by lines and filter out lines that contain unmatched image references
            lines = summary.split("\n")
            filtered_lines = []

            for line in lines:
                # Check if line contains markdown image syntax
                if re.search(r"!\[.*?\]\([^)]+\)", line):
                    # If it contains an image reference, check if it's a valid URL or still a placeholder
                    # Remove lines that contain placeholder-style references (not actual URLs)
                    image_refs = re.findall(r"!\[.*?\]\(([^)]+)\)", line)
                    has_unmatched_placeholder = False

                    for ref in image_refs:
                        # If it's not a proper URL (doesn't start with http/https) and looks like a placeholder
                        if not ref.startswith(
                            ("http://", "https://")
                        ) and not ref.startswith("/"):
                            has_unmatched_placeholder = True
                            break

                    # Only keep the line if it doesn't have unmatched placeholders
                    if not has_unmatched_placeholder:
                        filtered_lines.append(line)
                else:
                    filtered_lines.append(line)

            return "\n".join(filtered_lines)

        # Get the paper
        paper = self.get(db, id=paper_id, user=current_user)
        if not paper:
            raise ValueError(
                f"Paper with ID {paper_id} not found or doesn't belong to user"
            )

        paper_images = paper_image_crud.get_by_paper_id(
            db, paper_id=paper_id, user=current_user
        )

        # Get all image placeholders in the paper
        image_placeholders = _find_and_replace_all_placeholders(
            str(paper.summary), paper_images
        )

        return image_placeholders

    def get_summary_replace_image_placeholders_shared_paper(
        self, db: Session, *, paper_id: str
    ) -> str:
        """Replace image placeholders with actual images in a shared paper.

        Args:
            db (Session): Database session.
            paper_id (str): ID of the paper to update.
        """
        # Get the paper without a user context first
        paper = db.get(Document, paper_id)

        if not paper:
            raise ValueError(f"Paper with ID {paper_id} not found")

        public_entry = db.scalar(
            select(LibraryPaper).where(
                LibraryPaper.document_id == paper.id,
                LibraryPaper.is_public.is_(True),
            )
        )
        if public_entry is None:
            raise ValueError(f"Paper with ID {paper_id} is not a shared paper")

        user = db.get(AuthUser, public_entry.user_id)
        if not user:
            raise ValueError(f"User for paper with ID {paper_id} not found")

        current_user = CurrentUser.from_auth_user(user)

        # Call the original method with the created user
        return self.get_summary_replace_image_placeholders(
            db, paper_id=paper_id, current_user=current_user
        )

    def get_all_available_papers(
        self,
        db: Session,
        *,
        user: CurrentUser,
        query: str | None = None,
        paper_ids: list[str] | None = None,
    ) -> list[Document]:
        """
        Get all papers available to the user, regardless of status.
        This includes papers with 'todo', 'reading', and 'completed' statuses.
        If a query is provided, it will filter papers by raw_content.
        If paper_ids is provided, it will filter papers by the given list of IDs.
        """
        statement = (
            select(Document)
            .join(LibraryPaper, LibraryPaper.document_id == Document.id)
            .where(LibraryPaper.user_id == user.id)
        )

        if paper_ids:
            statement = statement.where(Document.id.in_(paper_ids))

        statement = statement.where(Document.ts_vector.isnot(None))

        if query:
            # The query is split into words and joined with '&' to create a tsquery.
            # This means all words in the query must be present in the document.
            ts_query = func.to_tsquery("english", " & ".join(query.split()))
            statement = statement.where(Document.ts_vector.op("@@")(ts_query))

        return list(db.scalars(statement.order_by(Document.updated_at.desc())).all())

    @staticmethod
    def build_passages(
        raw_content: str, window: int = 5, stride: int = 3
    ) -> list[PassageInsert]:
        """Split raw_content into overlapping passage windows."""
        lines = raw_content.split("\n")
        passages: list[PassageInsert] = []
        for i in range(0, len(lines), stride):
            chunk = lines[i : i + window]
            passages.append(
                {
                    "start_line": i + 1,  # 1-indexed
                    "end_line": i + len(chunk),  # 1-indexed
                    "content": "\n".join(chunk),
                }
            )
        return passages

    def index_paper_passages(
        self,
        db: Session,
        *,
        paper_id: uuid.UUID,
        raw_content: str,
        window: int = 5,
        stride: int = 3,
    ) -> None:
        """Index a paper's content as overlapping passages for FTS."""
        sanitized_raw_content = sanitize_for_postgres(raw_content)
        if sanitized_raw_content != raw_content:
            logger.warning(
                "Sanitized null characters before indexing passages for paper %s",
                paper_id,
            )

        db.execute(
            text("DELETE FROM scholens.paper_passages WHERE paper_id = :paper_id"),
            {"paper_id": paper_id},
        )

        passages = self.build_passages(
            sanitized_raw_content,
            window=window,
            stride=stride,
        )
        if passages:
            db.execute(
                text(
                    """
                    INSERT INTO scholens.paper_passages
                        (paper_id, start_line, end_line, content)
                    VALUES (:paper_id, :start_line, :end_line, :content)
                """
                ),
                [{"paper_id": paper_id, **p} for p in passages],
            )
        db.flush()

    def search_papers_and_get_matching_lines(
        self,
        db: Session,
        *,
        user: CurrentUser,
        query: str,
        paper_ids: list[uuid.UUID] | None = None,
    ) -> list[tuple[str, int, str]]:
        """
        Search for papers using passage-level FTS and return exact matching lines.

        Queries the paper_passages table (GIN-indexed tsvector per passage),
        then refines to exact lines with a cheap in-memory regex on the small
        passage content. Deduplicates lines that appear in overlapping windows.
        """
        sanitized_query = query.replace("-", " ")
        raw_terms = [
            term.strip() for term in sanitized_query.split("|") if term.strip()
        ]
        if not raw_terms:
            return []

        search_terms = list({t.lower() for t in raw_terms})

        # Build regex for in-memory line refinement
        regex_terms = [re.escape(term) for term in search_terms]
        regex_query = "|".join(regex_terms)

        # Build FTS query clause
        phrase_parts = []
        for i, term in enumerate(search_terms):
            phrase_parts.append(f"phraseto_tsquery('english', :term_{i})")
        fts_query_clause = " || ".join(phrase_parts)

        sql = f"""
            SELECT pp.paper_id::text, pp.start_line, pp.content
            FROM scholens.paper_passages pp
            JOIN scholens.documents d ON d.id = pp.paper_id
            JOIN scholens.library_papers lp ON lp.document_id = d.id
            WHERE pp.ts_vector @@ ({fts_query_clause})
              AND lp.user_id = :user_id
        """

        params: dict[str, object] = {"user_id": user.id}
        for i, term in enumerate(search_terms):
            params[f"term_{i}"] = term

        if paper_ids:
            sql += " AND pp.paper_id = ANY(:paper_ids)"
            params["paper_ids"] = paper_ids

        sql += " ORDER BY pp.paper_id, pp.start_line"

        raw_results = db.execute(text(sql), params).fetchall()

        # Refine: extract exact matching lines and deduplicate across
        # overlapping passage windows.
        seen: dict[tuple[str, int], tuple[str, int, str]] = {}
        for paper_id, start_line, content in raw_results:
            for offset, line in enumerate(content.split("\n")):
                if re.search(regex_query, line, re.IGNORECASE):
                    key = (paper_id, start_line + offset)
                    if key not in seen:
                        seen[key] = (paper_id, start_line + offset, line)

        return sorted(seen.values(), key=lambda r: (r[0], r[1]))

    def get_topics(
        self,
        db: Session,
        *,
        user: CurrentUser,
    ) -> list[str]:
        """
        Get a list of unique tags from all available papers.
        """
        rows = db.scalars(
            select(PaperTag.name)
            .join(PaperTag.library_papers)
            .where(
                PaperTag.user_id == user.id,
            )
            .distinct()
        ).all()

        return [name.strip() for name in rows if name and name.strip()]

    def add_to_library(
        self,
        db: Session,
        *,
        document: Document,
        user: CurrentUser,
    ) -> Document | None:
        existing = get_library_paper(
            db,
            document_id=document.id,
            user_id=user.id,
        )
        if existing is not None:
            return document
        db.add(
            LibraryPaper(
                user_id=user.id,
                document_id=document.id,
                status=PaperStatus.reading,
            )
        )
        db.commit()
        return document

    def get_by_doi_for_user(
        self, db: Session, *, user_id: int, doi: str
    ) -> Document | None:
        """Return the user's paper with a matching normalized DOI, if any."""
        normalized = normalize_doi(doi)
        if not normalized:
            return None

        # normalize_doi yields a bare, lowercased DOI (e.g. "10.1234/abc"). Stored
        # DOIs may carry a scheme/prefix (https://doi.org/…, doi:…) or different
        # casing, so match the normalized form as a case-insensitive suffix in the
        # database rather than scanning every paper in Python.
        escaped = (
            normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        return db.scalars(
            select(Document)
            .join(LibraryPaper, LibraryPaper.document_id == Document.id)
            .where(
                LibraryPaper.user_id == user_id,
                func.lower(Document.doi).like(f"%{escaped}", escape="\\"),
            )
        ).first()


# Create a single instance to use throughout the application
paper_crud = PaperCRUD(Document)
