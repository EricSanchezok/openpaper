from app.transport.http.public_v1.auth_dependencies import get_required_user
from app.database.crud.zotero_crud import zotero_crud
from app.database.crud.zotero_import_crud import zotero_import_crud
from app.database.database import get_db
from app.database.models import ZoteroImportedItem
from app.database.telemetry import track_event
from app.errors import AppError
from app.services.resource_quotas import can_user_upload_paper
from app.shared.application import Actor
from app.modules.integrations.zotero.application.contracts import (
    ZoteroImportError,
    ZoteroImportItemResult,
    ZoteroImportRequest,
    ZoteroImportResponse,
    ZoteroImportStatusItem,
    ZoteroImportStatusListResponse,
    ZoteroLibraryItem,
    ZoteroLibraryResponse,
    ZoteroSyncResponse,
)
from app.services.zotero.service import import_batch, list_library, sync_batch
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

zotero_router = APIRouter()


@zotero_router.get("/library", response_model=ZoteroLibraryResponse)
def zotero_library(
    current_user: Actor = Depends(get_required_user),
    db: Session = Depends(get_db),
) -> ZoteroLibraryResponse:
    """List importable journal articles, conference papers, and preprints from the user's Zotero library."""
    connection = zotero_crud.get_by_user_id(db, user_id=current_user.id)
    if not connection:
        raise AppError(
            code="zotero_not_connected",
            message="Connect a Zotero account before using this feature",
            status_code=400,
        )
    result = list_library(db, user=current_user)

    return ZoteroLibraryResponse(
        items=[ZoteroLibraryItem(**item) for item in result["items"]],
        remaining_slots=result["remaining_slots"],
    )


@zotero_router.post("/import", response_model=ZoteroImportResponse)
async def zotero_import(
    request: ZoteroImportRequest,
    current_user: Actor = Depends(get_required_user),
    db: Session = Depends(get_db),
) -> ZoteroImportResponse:
    """Import selected journal articles, conference papers, and preprints from Zotero (PDF or URL fallback)."""
    connection = zotero_crud.get_by_user_id(db, user_id=current_user.id)
    if not connection:
        raise AppError(
            code="zotero_not_connected",
            message="Connect a Zotero account before importing",
            status_code=400,
        )

    can_upload, upload_err = can_user_upload_paper(db, current_user)
    if not can_upload:
        raise AppError(
            code="paper_quota_exceeded",
            message=upload_err or "Upload limit reached",
            status_code=403,
        )

    try:
        result = await import_batch(db, user=current_user, item_keys=request.item_keys)
    except ValueError as exc:
        raise AppError(
            code="zotero_import_invalid",
            message="The selected Zotero items could not be imported",
            status_code=400,
        ) from exc

    if result["imported_count"] > 0:
        track_event(
            "zotero_import_batch",
            user_id=str(current_user.id),
            properties={"count": result["imported_count"]},
            db=db,
        )

    return ZoteroImportResponse(
        imported=[ZoteroImportItemResult(**item) for item in result["imported"]],
        imported_count=result["imported_count"],
        imported_via_url=result["imported_via_url"],
        skipped_already_imported=result["skipped_already_imported"],
        errors=[ZoteroImportError(**err) for err in result["errors"]],
    )


@zotero_router.post("/sync", response_model=ZoteroSyncResponse)
async def zotero_sync(
    current_user: Actor = Depends(get_required_user),
    db: Session = Depends(get_db),
) -> ZoteroSyncResponse:
    """Manually trigger annotation sync for all already-imported Zotero PDF papers. Available to all plan tiers."""
    connection = zotero_crud.get_by_user_id(db, user_id=current_user.id)
    if not connection:
        raise AppError(
            code="zotero_not_connected",
            message="Connect a Zotero account before synchronizing",
            status_code=400,
        )

    result = await sync_batch(db, user=current_user, limit=50)

    if result.get("new_annotations_count", 0) > 0:
        track_event(
            "zotero_manual_sync",
            user_id=str(current_user.id),
            properties={
                "papers": result.get("synced_papers_count", 0),
                "annotations": result.get("new_annotations_count", 0),
            },
            db=db,
        )

    return ZoteroSyncResponse(
        synced_papers_count=result["synced_papers_count"],
        new_annotations_count=result["new_annotations_count"],
    )


def _zotero_import_status_items(
    rows: list[tuple[ZoteroImportedItem, str | None]],
) -> list[ZoteroImportStatusItem]:
    return [
        ZoteroImportStatusItem(
            zotero_item_key=row.zotero_item_key,
            document_id=str(row.document_id) if row.document_id else None,
            upload_job_id=str(row.upload_job_id) if row.upload_job_id else None,
            import_source=row.import_source,
            status=row.status,
            title=title,
            error_message=row.error_message,
            created_at=row.created_at,
            last_synced_at=row.last_synced_at,
        )
        for row, title in rows
    ]


@zotero_router.get("/import/status", response_model=ZoteroImportStatusListResponse)
async def zotero_import_status_list(
    item_keys: list[str] | None = Query(None),
    current_user: Actor = Depends(get_required_user),
    db: Session = Depends(get_db),
) -> ZoteroImportStatusListResponse:
    """List recent Zotero import records for the current user."""
    if item_keys:
        rows = zotero_import_crud.list_by_item_keys(
            db, user_id=current_user.id, item_keys=item_keys
        )
    else:
        rows = zotero_import_crud.list_recent_by_user(db, user_id=current_user.id)
    items = _zotero_import_status_items(rows)
    return ZoteroImportStatusListResponse(items=items)
