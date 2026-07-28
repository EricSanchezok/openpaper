from starlette.responses import Response as ApiResponse
import hashlib
import logging

from app.auth.dependencies import get_current_user, get_required_user
from app.database.crud.paper_crud import PaperUpdate, paper_crud
from app.database.crud.paper_upload_crud import paper_upload_job_crud
from app.database.database import get_db
from app.database.models import (
    AuthUser,
    Document,
    LibraryPaper,
    PaperStatus,
    PaperTag,
    ZoteroImportedItem,
)
from app.database.telemetry import track_event
from app.helpers.metadata_hydration import hydrate_paper_metadata
from app.helpers.s3 import s3_service
from app.services.resource_quotas import can_user_upload_paper
from app.schemas.orm_responses import (
    serialize_paper,
)
from app.schemas.responses import ResponseCitation
from app.schemas.user import CurrentUser
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

load_dotenv()

logger = logging.getLogger(__name__)

# Create API router with prefix
paper_router = APIRouter()


class SharePaperSchemaResponse(BaseModel):
    paper_data: dict[str, object]
    highlight_data: dict[str, object]
    annotations_data: dict[str, object]


class UpdatePaperFieldsSchema(BaseModel):
    title: str | None = None
    authors: list[str] | None = None
    abstract: str | None = None
    institutions: list[str] | None = None
    publish_date: str | None = None
    doi: str | None = None
    journal: str | None = None
    publisher: str | None = None


def _serialize_paper_for_client(
    paper: Document,
    *,
    library_paper: LibraryPaper | None = None,
    tags: list[PaperTag] | None = None,
) -> dict[str, object]:
    data: dict[str, object] = dict(serialize_paper(paper))
    data["status"] = (
        library_paper.status if library_paper is not None else PaperStatus.reading
    )
    data["last_accessed_at"] = (
        library_paper.last_accessed_at.isoformat()
        if library_paper is not None
        else None
    )
    data["is_public"] = library_paper.is_public if library_paper else False
    data["share_id"] = None
    data["tags"] = [
        {"id": str(tag.id), "name": tag.name, "color": tag.color} for tag in tags or []
    ]
    data["preview_url"] = _presigned_preview_url(paper)
    return data


def _presigned_preview_url(paper: Document) -> str | None:
    if not paper.preview_s3_key:
        return None
    return s3_service.generate_presigned_url(paper.preview_s3_key)


@paper_router.get("/all")
async def get_paper_ids(
    db: Session = Depends(get_db),
    detailed: bool = False,
    current_user: CurrentUser = Depends(get_required_user),
) -> ApiResponse:
    """
    Get all paper IDs
    """
    papers: list[Document] = paper_crud.get_multi_uploads_completed(
        db, user=current_user
    )
    document_ids = [paper.id for paper in papers]
    library_by_document = paper_crud.get_library_papers(
        db,
        document_ids=document_ids,
        user=current_user,
    )
    tags_by_document = paper_crud.get_tags_by_document_ids(
        db,
        document_ids=document_ids,
        user=current_user,
    )

    file_urls: dict[str, str] = {}
    if detailed:
        file_urls = s3_service.generate_presigned_urls(
            {str(paper.id): paper.s3_object_key for paper in papers}
        )

    data = [
        {
            "id": str(paper.id),
            "title": paper.title,
            "created_at": str(paper.created_at),
            "abstract": paper.abstract,
            "authors": paper.authors,
            "institutions": paper.institutions,
            "status": library_by_document[paper.id].status,
            "preview_url": _presigned_preview_url(paper),
            "size_in_kb": (paper.size_bytes + 1023) // 1024,
            "parser_quality": paper.parser_quality,
            "parser_warning_code": paper.parser_warning_code,
            "publish_date": (str(paper.publish_date) if paper.publish_date else None),
            "file_url": file_urls.get(str(paper.id)),
            "tags": [
                {"id": str(tag.id), "name": tag.name, "color": tag.color}
                for tag in tags_by_document.get(paper.id, [])
            ],
        }
        for paper in papers
    ]
    return JSONResponse(
        status_code=200,
        content={"papers": data},
    )


@paper_router.get("/active")
async def get_active_paper_ids(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ApiResponse:
    """
    Get all active paper IDs
    """
    papers: list[Document] = paper_crud.get_multi_uploads_completed(
        db, user=current_user, status=PaperStatus.reading
    )
    library_by_document = paper_crud.get_library_papers(
        db,
        document_ids=[paper.id for paper in papers],
        user=current_user,
    )

    data = [
        {
            "id": str(paper.id),
            "title": paper.title,
            "created_at": str(paper.created_at),
            "abstract": paper.abstract,
            "authors": paper.authors,
            "institutions": paper.institutions,
            "status": library_by_document[paper.id].status,
            "preview_url": _presigned_preview_url(paper),
            "size_in_kb": (paper.size_bytes + 1023) // 1024,
            "parser_quality": paper.parser_quality,
            "parser_warning_code": paper.parser_warning_code,
            "publish_date": (str(paper.publish_date) if paper.publish_date else None),
        }
        for paper in papers
    ]

    return JSONResponse(
        status_code=200,
        content={"papers": data},
    )


@paper_router.get("/pending-jobs")
async def get_user_pending_jobs(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """
    Get the user's in-progress upload jobs across their whole library, so the
    Library page can rehydrate the upload tracker after a refresh. Dead jobs are
    filtered out server-side (see STALE_UPLOAD_JOB_CUTOFF).
    """
    try:
        jobs = paper_upload_job_crud.get_in_progress_jobs_for_user(
            db, user=current_user
        )

        return JSONResponse(
            status_code=200,
            content={
                "jobs": [
                    {
                        "job_id": str(job.id),
                        "status": job.status,
                        "paper_id": str(paper.id),
                        "title": paper.title,
                        "started_at": (
                            job.started_at.isoformat() if job.started_at else None
                        ),
                    }
                    for job, paper in jobs
                ]
            },
        )

    except Exception as e:
        logger.error(f"Error fetching pending upload jobs: {e}", exc_info=True)
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to fetch pending upload jobs"},
        )


@paper_router.get("/{id}/file-url")
async def get_paper_file_url(
    id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """
    Get a fresh presigned file URL for a single owned paper.

    This is the cheap path for "my URL expired, give me a fresh one" — it
    avoids the metadata enrichment and full document payload (raw_content,
    etc.) that GET /api/paper returns.
    """
    paper = paper_crud.get(db, id=id, user=current_user)
    if not paper:
        return JSONResponse(status_code=404, content={"message": "Paper not found"})

    file_url = s3_service.generate_presigned_url(paper.s3_object_key)

    return JSONResponse(status_code=200, content={"file_url": file_url})


@paper_router.post("/status")
async def set_paper_status(
    paper_id: str,
    status: PaperStatus,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ApiResponse:
    """
    Set the status of a paper
    """
    target_paper = paper_crud.get(db, id=paper_id, user=current_user)

    if not target_paper:
        raise HTTPException(status_code=404, detail=f"No document with id {paper_id}")

    paper_update = PaperUpdate(status=status)
    updated_paper = paper_crud.update(
        db=db, db_obj=target_paper, obj_in=paper_update, user=current_user
    )

    if not updated_paper:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update paper status for document ID {paper_id}",
        )

    track_event(
        "paper_status_updated",
        properties={
            "paper_id": str(updated_paper.id),
            "status": status.value,
        },
        user_id=str(current_user.id),
        db=db,
    )

    return JSONResponse(
        content=_serialize_paper_for_client(
            updated_paper,
            library_paper=paper_crud.get_library_paper(
                db,
                document_id=updated_paper.id,
                user=current_user,
            ),
        ),
        status_code=200,
    )


@paper_router.patch("")
async def update_paper_fields(
    paper_id: str,
    request: UpdatePaperFieldsSchema,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ApiResponse:
    """
    Update editable fields of a paper (title, authors, abstract, etc.)
    """
    target_paper = paper_crud.get(db, id=paper_id, user=current_user)

    if not target_paper:
        raise HTTPException(status_code=404, detail=f"No document with id {paper_id}")

    update_data = request.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    updated_paper = paper_crud.update(
        db=db, db_obj=target_paper, obj_in=update_data, user=current_user
    )

    if not updated_paper:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update paper fields for document ID {paper_id}",
        )

    track_event(
        "paper_fields_updated",
        properties={
            "paper_id": str(updated_paper.id),
            "updated_fields": list(update_data.keys()),
        },
        user_id=str(current_user.id),
        db=db,
    )

    return JSONResponse(
        content=_serialize_paper_for_client(
            updated_paper,
            library_paper=paper_crud.get_library_paper(
                db,
                document_id=updated_paper.id,
                user=current_user,
            ),
        ),
        status_code=200,
    )


@paper_router.get("/relevant")
async def get_relevant_papers(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ApiResponse:
    """
    Get the most relevant papers uploaded by the user
    """
    papers: list[Document] = paper_crud.get_top_relevant_papers(db, user=current_user)
    library_by_document = paper_crud.get_library_papers(
        db,
        document_ids=[paper.id for paper in papers],
        user=current_user,
    )

    return JSONResponse(
        status_code=200,
        content={
            "papers": [
                {
                    "id": str(paper.id),
                    "title": paper.title,
                    "created_at": str(paper.created_at),
                    "abstract": paper.abstract,
                    "authors": paper.authors,
                    "institutions": paper.institutions,
                    "status": library_by_document[paper.id].status,
                    "preview_url": _presigned_preview_url(paper),
                    "size_in_kb": (paper.size_bytes + 1023) // 1024,
                }
                for paper in papers
            ]
        },
    )


@paper_router.get("")
async def get_pdf(
    request: Request,
    id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ApiResponse:
    """
    Get a document by ID
    """
    # Fetch the document from the database
    paper = paper_crud.get(db, id=id, user=current_user, update_last_accessed=True)

    if not paper:
        return JSONResponse(status_code=404, content={"message": "Paper not found"})

    signed_url = s3_service.generate_presigned_url(paper.s3_object_key)

    paper = hydrate_paper_metadata(db=db, paper=paper, user=current_user)

    library_paper = paper_crud.get_library_paper(
        db,
        document_id=paper.id,
        user=current_user,
    )
    tags = paper_crud.get_tags_by_document_ids(
        db,
        document_ids=[paper.id],
        user=current_user,
    ).get(paper.id, [])
    paper_data = _serialize_paper_for_client(
        paper,
        library_paper=library_paper,
        tags=tags,
    )
    paper_data["file_url"] = signed_url
    paper_data["summary_citations"] = [
        ResponseCitation.model_validate(citation).model_dump()
        for citation in paper.summary_citations or []
    ]

    paper_data["summary"] = paper_crud.get_summary_replace_image_placeholders(
        db, paper_id=id, current_user=current_user
    )

    # Flag whether this paper originated from a Zotero import (surfaced as a
    # provenance badge in the library detail panel).
    paper_data["zotero_synced"] = (
        db.scalar(
            select(ZoteroImportedItem.id)
            .where(
                ZoteroImportedItem.paper_id == paper.id,
                ZoteroImportedItem.user_id == current_user.id,
            )
            .limit(1)
        )
        is not None
    )

    # Return the file URL
    return JSONResponse(status_code=200, content=paper_data)


@paper_router.post("/share")
async def share_pdf(
    request: Request,
    id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ApiResponse:
    """
    Share a document by ID
    """
    # Fetch the document from the database
    paper = paper_crud.get(db, id=id, user=current_user)

    if not paper:
        return JSONResponse(status_code=404, content={"message": "Paper not found"})

    shared = paper_crud.make_public(db, paper_id=id, user=current_user)
    if shared is None:
        return JSONResponse(status_code=404, content={"message": "Paper not found"})
    _, share_token = shared
    library_paper = paper_crud.get_library_paper(
        db,
        document_id=paper.id,
        user=current_user,
    )
    if library_paper is None:
        return JSONResponse(
            status_code=404,
            content={"message": "Paper is not in your library"},
        )

    track_event(
        "paper_share",
        properties={
            "paper_id": str(paper.id),
            "share_id": share_token,
        },
        user_id=str(current_user.id),
        db=db,
    )

    # Return the updated sharing state so the client can use it as the source of truth
    return JSONResponse(
        status_code=200,
        content={
            "message": "Document shared successfully",
            "share_id": share_token,
            "is_public": library_paper.is_public,
        },
    )


@paper_router.post("/unshare")
async def unshare_pdf(
    request: Request,
    id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ApiResponse:
    """
    Unshare a document by ID
    """
    # Fetch the document from the database
    paper = paper_crud.get(db, id=id, user=current_user)

    if not paper:
        return JSONResponse(status_code=404, content={"message": "Paper not found"})

    paper_crud.make_private(db, paper_id=id, user=current_user)
    library_paper = paper_crud.get_library_paper(
        db,
        document_id=paper.id,
        user=current_user,
    )
    if library_paper is None:
        return JSONResponse(
            status_code=404,
            content={"message": "Paper is not in your library"},
        )

    track_event(
        "paper_unshare",
        properties={
            "paper_id": str(paper.id),
            "share_id": None,
        },
        user_id=str(current_user.id),
        db=db,
    )

    # Return the updated sharing state so the client can use it as the source of truth
    return JSONResponse(
        status_code=200,
        content={
            "message": "Document unshared successfully",
            "share_id": None,
            "is_public": library_paper.is_public,
        },
    )


@paper_router.get("/share")
async def get_shared_pdf(
    request: Request,
    id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> ApiResponse:
    """
    Get a shared document by ID
    """
    # Fetch the document from the database
    response: dict[str, object] = {}

    paper = paper_crud.get_public_paper(db, share_id=id)
    public_entry = paper_crud.get_public_library_paper(db, share_id=id)

    if not paper or public_entry is None:
        return JSONResponse(status_code=404, content={"message": "Paper not found"})

    paper_data = _serialize_paper_for_client(
        paper,
        library_paper=public_entry,
    )

    signed_url = s3_service.generate_presigned_url(paper.s3_object_key)

    paper_data["file_url"] = signed_url
    paper_data["summary_citations"] = [
        ResponseCitation.model_validate(citation).model_dump()
        for citation in paper.summary_citations or []
    ]
    paper_data["summary"] = (
        paper_crud.get_summary_replace_image_placeholders_shared_paper(
            db, paper_id=str(paper.id)
        )
    )
    response["paper"] = paper_data
    owner = db.get(AuthUser, public_entry.user_id)
    if owner is None:
        return JSONResponse(
            status_code=404, content={"message": "Document owner not found"}
        )
    response["owner"] = {
        "display_name": owner.display_name or owner.email,
        "id": str(owner.id),
    }

    track_event(
        "paper_shared_view",
        properties={
            "paper_id": str(paper.id),
            "share_id": hashlib.sha256(id.encode()).hexdigest()[:12],
        },
        user_id=str(current_user.id) if current_user else None,
        db=db,
    )

    # Return the file URL
    return JSONResponse(status_code=200, content=response)


@paper_router.delete("")
async def delete_pdf(
    request: Request,
    id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ApiResponse:
    """
    Delete a document by ID
    """
    # Fetch the document from the database
    paper = paper_crud.get(db, id=id, user=current_user)

    if not paper:
        return JSONResponse(status_code=404, content={"message": "Paper not found"})

    try:
        removed_paper = paper_crud.remove(db, id=id, user=current_user)
        if not removed_paper:
            return JSONResponse(
                status_code=500,
                content={"message": "Failed to remove paper from library"},
            )

        return JSONResponse(
            status_code=200,
            content={"message": "Paper removed from library"},
        )
    except Exception:
        logger.error("Error deleting document")
        return JSONResponse(
            status_code=500,
            content={"message": "Error deleting document"},
        )


class CollectSharedPaperRequest(BaseModel):
    share_id: str


@paper_router.post("/collect")
async def collect_shared_paper(
    request: CollectSharedPaperRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """
    Add an already-stored public document to the current user's library.
    """
    try:
        can_upload, error_message = can_user_upload_paper(db, current_user)
        if not can_upload:
            return JSONResponse(
                status_code=403,
                content={"message": error_message},
            )

        shared_paper = paper_crud.get_public_paper(db, share_id=request.share_id)

        if not shared_paper:
            raise HTTPException(
                status_code=404,
                detail="Shared paper not found or is no longer public.",
            )

        existing = paper_crud.get_library_paper(
            db,
            document_id=shared_paper.id,
            user=current_user,
        )
        if existing is not None:
            return JSONResponse(
                status_code=200,
                content={
                    "message": "You already have this paper in your library",
                    "paper_id": str(shared_paper.id),
                    "already_exists": True,
                },
            )

        collected = paper_crud.add_to_library(
            db,
            document=shared_paper,
            user=current_user,
        )

        if collected is None:
            raise HTTPException(
                status_code=500,
                detail="Failed to collect paper.",
            )

        track_event(
            "paper_collected_from_share",
            user_id=str(current_user.id),
            properties={
                "share_id": request.share_id,
                "paper_id": str(shared_paper.id),
            },
            db=db,
        )

        return JSONResponse(
            status_code=201,
            content={
                "message": "Paper added to your library",
                "paper_id": str(shared_paper.id),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error collecting shared paper: {e}", exc_info=True)
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to collect shared paper"},
        )
