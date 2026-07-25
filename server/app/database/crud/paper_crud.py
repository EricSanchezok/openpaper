import logging
import re
import uuid
from datetime import datetime
from typing import TypedDict

from app.database.crud.annotation_crud import AnnotationCreate, annotation_crud
from app.database.crud.base_crud import CRUDBase
from app.database.crud.highlight_crud import HighlightCreate, highlight_crud
from app.database.crud.paper_image_crud import paper_image_crud
from app.database.crud.paper_tag_crud import paper_tag_crud
from app.database.crud.sanitization import sanitize_for_postgres
from app.database.models import (
    AuthUser,
    Highlight,
    JobStatus,
    JsonValue,
    Paper,
    PaperImage,
    PaperStatus,
    PaperTag,
    PaperUploadJob,
    RoleType,
)
from app.helpers.paper_search import normalize_doi
from app.helpers.parser import get_start_page_from_offset
from app.llm.utils import find_offsets
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
    file_url: str | None = None
    s3_object_key: str | None = None
    authors: list[str] | None = None
    title: str | None = None
    abstract: str | None = None
    institutions: list[str] | None = None
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
    upload_job_id: str | None = None
    preview_url: str | None = None
    size_in_kb: int | None = None
    # We can't save tuples in the db, so we use a list (length 2) to represent page offsets
    page_offset_map: dict[int, list[int]] | None = None


class PaperCreate(PaperBase):
    # Only mandate required fields for creation, others are optional
    file_url: str
    raw_content: str | None = None
    s3_object_key: str | None = None
    upload_job_id: str | None = None
    preview_url: str | None = None
    parent_paper_id: uuid.UUID | None = None


class PaperUpdate(PaperBase):
    status: PaperStatus | None = PaperStatus.todo
    cached_presigned_url: str | None = None
    presigned_url_expires_at: datetime | None = None
    preview_url: str | None = None
    raw_content: str | None = None
    doi: str | None = None
    size_in_kb: int | None = None
    journal: str | None = None
    publisher: str | None = None
    attempted_metadata_at: datetime | None = None
    field_provenance: dict[str, JsonValue] | None = None


class PaperDocumentMetadata(BaseModel):
    raw_content: str | None = None
    page_offsets: dict[int, tuple[int, int]] | None = None


# Paper CRUD that inherits from the base CRUD
class PaperCRUD(CRUDBase["Paper", PaperCreate, PaperUpdate]):
    """CRUD operations specifically for Document model"""

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
        paper: Paper | None = self.get(db, paper_id, user=current_user)
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
    ) -> list[Paper]:
        """
        Get recent papers with priority logic:
        1. Order by most recently uploaded
        2. First get papers with 'reading' status
        3. If under limit, fill with 'todo' status papers
        4. Return up to limit papers
        """
        # First, get reading papers
        reading_papers = db.scalars(
            select(Paper)
            .where(Paper.user_id == user.id, Paper.status == PaperStatus.reading)
            .join(
                PaperUploadJob, Paper.upload_job_id == PaperUploadJob.id, isouter=True
            )
            .where(
                (PaperUploadJob.status == JobStatus.COMPLETED)
                | (Paper.upload_job_id.is_(None))
            )
            .order_by(Paper.last_accessed_at.desc())
            .limit(limit)
        ).all()

        # If we have enough reading papers, return them
        if len(reading_papers) >= limit:
            return list(reading_papers)

        # Calculate how many more papers we need
        remaining_limit = limit - len(reading_papers)

        # Get todo papers to fill the remaining slots
        todo_papers = db.scalars(
            select(Paper)
            .where(Paper.user_id == user.id, Paper.status == PaperStatus.todo)
            .order_by(Paper.last_accessed_at.desc())
            .limit(remaining_limit)
        ).all()

        # Combine and return
        return list(reading_papers) + list(todo_papers)

    def get_size_of_knowledge_base(self, db: Session, *, user: CurrentUser) -> int:
        """
        Get the total size of the user's knowledge base in KB.
        This includes all papers that have completed uploads.
        """
        from app.helpers.s3 import s3_service

        # First, get papers with missing size_in_kb and update them
        papers_without_size = db.scalars(
            select(Paper)
            .outerjoin(PaperUploadJob, Paper.upload_job_id == PaperUploadJob.id)
            .where(
                Paper.user_id == user.id,
                (
                    Paper.upload_job_id.is_(None)  # No upload job (direct uploads)
                    | (
                        PaperUploadJob.status == JobStatus.COMPLETED
                    )  # Or job is completed
                ),
                Paper.size_in_kb.is_(None),  # Only papers without size_in_kb
                Paper.s3_object_key.isnot(None),  # Must have S3 object key
            )
        ).all()

        # Update papers that don't have size_in_kb set
        for paper in papers_without_size:
            if paper.s3_object_key:
                paper_size_in_kb = s3_service.get_file_size_in_kb(
                    str(paper.s3_object_key)
                )
                if paper_size_in_kb:
                    # Update the paper's size_in_kb field in the database
                    update_paper = PaperUpdate(size_in_kb=paper_size_in_kb)
                    self.update(db, db_obj=paper, obj_in=update_paper)

        # Now get all completed papers and sum their sizes
        total_size = db.scalar(
            select(func.coalesce(func.sum(Paper.size_in_kb), 0))
            .outerjoin(PaperUploadJob, Paper.upload_job_id == PaperUploadJob.id)
            .where(
                Paper.user_id == user.id,
                (
                    Paper.upload_job_id.is_(None)  # No upload job (direct uploads)
                    | (
                        PaperUploadJob.status == JobStatus.COMPLETED
                    )  # Or job is completed
                ),
            )
        )
        return int(total_size or 0)

    def make_public(
        self, db: Session, *, paper_id: str, user: CurrentUser
    ) -> Paper | None:
        """Make a paper publicly accessible via share link"""
        paper = self.get(db, id=paper_id, user=user)
        if paper:
            # Generate a unique share ID if not already present
            if not paper.share_id:
                paper.share_id = str(uuid.uuid4())
            paper.is_public = True
            db.commit()
            db.refresh(paper)
        return paper

    def make_private(
        self, db: Session, *, paper_id: str, user: CurrentUser
    ) -> Paper | None:
        """Make a paper private (not publicly accessible)"""
        paper = self.get(db, id=paper_id, user=user)
        if paper:
            paper.is_public = False
            db.commit()
            db.refresh(paper)
        return paper

    def get_public_paper(self, db: Session, *, share_id: str) -> Paper | None:
        """Get a paper by its share_id if it's public"""
        return db.scalars(
            select(Paper).where(Paper.share_id == share_id, Paper.is_public.is_(True))
        ).first()

    def get_by_upload_job_id(
        self, db: Session, *, upload_job_id: str, user: CurrentUser
    ) -> Paper | None:
        """Get a paper by its upload job ID"""
        return db.scalars(
            select(Paper).where(
                Paper.upload_job_id == upload_job_id, Paper.user_id == user.id
            )
        ).first()

    def get_total_paper_count(self, db: Session, *, user: CurrentUser) -> int:
        """
        Get the total number of papers uploaded by a user.
        This includes all papers that have completed uploads.
        """
        return int(
            db.scalar(
                select(func.count(Paper.id))
                .outerjoin(PaperUploadJob, Paper.upload_job_id == PaperUploadJob.id)
                .where(
                    Paper.user_id == user.id,
                    (
                        Paper.upload_job_id.is_(None)  # No upload job (direct uploads)
                        | (
                            PaperUploadJob.status == JobStatus.COMPLETED
                        )  # Or job is completed
                    ),
                )
            )
            or 0
        )

    def get_multi_uploads_completed(
        self,
        db: Session,
        *,
        user: CurrentUser,
        skip: int = 0,
        limit: int = 500,
        status: PaperStatus | None = None,
    ) -> list[Paper]:
        """
        Get multiple papers that have completed uploads
        Completed uploads are those either with a null upload_job_id OR an upload_job with status 'completed'.
        """
        statement = (
            select(Paper)
            .options(
                selectinload(Paper.tags),
                # Library listings only need lightweight metadata. Without this,
                # the query SELECT *'s heavy columns (raw_content, ts_vector,
                # summary, summary_citations, page_offset_map) for every paper
                # in the user's library. Both callers (/api/paper/all and
                # /api/paper/active) serialize only the columns listed here.
                load_only(
                    Paper.title,
                    Paper.created_at,
                    Paper.updated_at,
                    Paper.abstract,
                    Paper.authors,
                    Paper.institutions,
                    Paper.status,
                    Paper.preview_url,
                    Paper.size_in_kb,
                    Paper.publish_date,
                ),
            )
            .outerjoin(PaperUploadJob, Paper.upload_job_id == PaperUploadJob.id)
            .where(
                Paper.user_id == user.id,
                (
                    Paper.upload_job_id.is_(None)  # No upload job (direct uploads)
                    | (
                        PaperUploadJob.status == JobStatus.COMPLETED
                    )  # Or job is completed
                ),
            )
            .order_by(Paper.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        if status:
            statement = statement.where(Paper.status == status)
        return list(db.scalars(statement).all())

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
                summary = summary.replace(placeholder, f"({image.image_url})")

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
        paper = db.get(Paper, paper_id)

        if not paper:
            raise ValueError(f"Paper with ID {paper_id} not found")

        # Verify the paper is public
        if not paper.is_public:
            raise ValueError(f"Paper with ID {paper_id} is not a shared paper")

        user = db.get(AuthUser, paper.user_id)
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
    ) -> list[Paper]:
        """
        Get all papers available to the user, regardless of status.
        This includes papers with 'todo', 'reading', and 'completed' statuses.
        If a query is provided, it will filter papers by raw_content.
        If paper_ids is provided, it will filter papers by the given list of IDs.
        """
        # Eager-load tags in a single batched query: callers like the evidence
        # pipeline read paper.tags per paper, which would otherwise N+1.
        statement = (
            select(Paper)
            .options(selectinload(Paper.tags))
            .where(Paper.user_id == user.id)
        )

        if paper_ids:
            statement = statement.where(Paper.id.in_(paper_ids))

        statement = statement.where(Paper.ts_vector.isnot(None))

        if query:
            # The query is split into words and joined with '&' to create a tsquery.
            # This means all words in the query must be present in the document.
            ts_query = func.to_tsquery("english", " & ".join(query.split()))
            statement = statement.where(Paper.ts_vector.op("@@")(ts_query))

        return list(db.scalars(statement.order_by(Paper.updated_at.desc())).all())

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
            JOIN scholens.papers p ON p.id = pp.paper_id
            WHERE pp.ts_vector @@ ({fts_query_clause})
              AND p.user_id = :user_id
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
            .join(PaperTag.papers)
            .where(
                PaperTag.user_id == user.id,
                Paper.user_id == user.id,
                Paper.ts_vector.isnot(None),
            )
            .distinct()
        ).all()

        return [name.strip() for name in rows if name and name.strip()]

    def get_forked_paper_by_parent_id(
        self, db: Session, *, parent_paper_id: uuid.UUID, user: CurrentUser
    ) -> Paper | None:
        """
        Find a forked paper by its parent_paper_id for the current user.
        A user can only have one fork of a given paper.
        """
        return db.scalars(
            select(Paper).where(
                Paper.parent_paper_id == parent_paper_id,
                Paper.user_id == user.id,
            )
        ).one_or_none()

    def fork_paper(
        self,
        db: Session,
        *,
        original_paper: Paper,
        new_file_object_key: str,
        new_file_url: str,
        new_preview_url: str | None,
        current_user: CurrentUser,
    ) -> Paper | None:
        """
        Fork a paper to create a duplicate for the current user.

        Args:
            original_paper: The paper to fork
            new_file_object_key: S3 object key for the forked paper's file
            new_file_url: URL for the forked paper's file
            new_preview_url: Optional preview URL for the forked paper
            current_user: The user creating the fork

        Returns:
            The newly created forked paper, or None if creation failed
        """
        # Create a new PaperCreate object with the same data as the original
        # TODO: Include AI highlights/annotations as well? See function used during intake `create_ai_annotations` for reference.
        new_paper_data = PaperCreate(
            file_url=new_file_url,
            s3_object_key=new_file_object_key,
            authors=original_paper.authors,
            title=str(original_paper.title),
            abstract=str(original_paper.abstract),
            institutions=original_paper.institutions,
            summary=str(original_paper.summary),
            summary_citations=None,
            starter_questions=original_paper.starter_questions,
            publish_date=str(original_paper.publish_date)
            if original_paper.publish_date
            else None,
            raw_content=original_paper.raw_content,
            upload_job_id=None,  # New upload job ID
            preview_url=new_preview_url,
            size_in_kb=(
                int(original_paper.size_in_kb)
                if original_paper.size_in_kb is not None
                else None
            ),
            parent_paper_id=uuid.UUID(str(original_paper.id)),  # Set parent paper ID
        )

        # Create the new paper in the database
        forked_paper = self.create(db, obj_in=new_paper_data, user=current_user)

        # Copy the original paper's tags onto the fork. Tags are user-scoped, so
        # this reuses the forking user's existing tags (case-insensitive) or
        # creates new ones, then links them to the forked paper.
        if forked_paper and original_paper.tags:
            try:
                paper_tag_crud.apply_keyword_tags(
                    db,
                    paper_id=uuid.UUID(str(forked_paper.id)),
                    keywords=[str(tag.name) for tag in original_paper.tags if tag.name],
                    user_id=current_user.id,
                )
            except Exception as e:
                logger.error(
                    f"Error copying tags to forked paper {forked_paper.id}: {e}",
                    exc_info=True,
                )

        # Index passages for the forked paper
        if forked_paper and original_paper.raw_content:
            try:
                self.index_paper_passages(
                    db,
                    paper_id=uuid.UUID(str(forked_paper.id)),
                    raw_content=str(original_paper.raw_content),
                )
            except Exception as e:
                logger.error(
                    f"Error indexing passages for forked paper {forked_paper.id}: {e}",
                    exc_info=True,
                )

        return forked_paper

    def get_by_doi_for_user(
        self, db: Session, *, user_id: int, doi: str
    ) -> Paper | None:
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
            select(Paper).where(
                Paper.user_id == user_id,
                func.lower(Paper.doi).like(f"%{escaped}", escape="\\"),
            )
        ).first()


# Create a single instance to use throughout the application
paper_crud = PaperCRUD(Paper)
