"""Zotero import and synchronization orchestration."""

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict, cast
from uuid import UUID

from app.repositories.upload_reservations import upload_reservation_repository
from app.database.crud.zotero_crud import zotero_crud
from app.database.crud.zotero_import_crud import zotero_import_crud
from app.database.database import SessionLocal
from app.database.models import (
    Document,
    RoleType,
    ZoteroImportedItem,
    ZoteroImportSource,
    ZoteroImportStatus,
)
from app.helpers.paper_search import normalize_doi
from app.helpers.parser import (
    extract_pdf_page_dimensions,
    validate_pdf_content,
    validate_url_and_fetch_pdf,
)
from app.helpers.s3 import s3_service
from app.services.resource_quotas import (
    can_user_upload_paper,
    get_remaining_paper_upload_slots,
)
from app.integrations.zotero_api import ZoteroApiClient
from app.llm.utils import find_offsets
from app.repositories.documents import document_repository
from app.repositories.library_tags import library_tag_repository
from app.repositories.research import HighlightThreadCreate, research_repository
from app.schemas.documents import DocumentUpdate
from app.schemas.user import CurrentUser
from app.services.document_annotations import require_parsed_content
from app.services.upload_reservations import reserve_upload
from app.services.document_submission import submit_reserved_document
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

ZOTERO_IMPORT_CONCURRENCY = 10


class ImportErrorResult(TypedDict):
    status: Literal["error"]
    zotero_item_key: str
    error: str


class ImportProcessingResult(TypedDict):
    status: Literal["processing"]
    zotero_item_key: str
    paper_id: str
    upload_job_id: str
    import_source: str
    title: str | None
    imported_via_url: bool


# Discriminated on `status` so success-only keys (paper_id, etc.) narrow safely.
ImportOneResult = ImportErrorResult | ImportProcessingResult


def _parse_zotero_date_added(date_str: str | datetime | None) -> datetime | None:
    """Parse Zotero item.data.dateAdded (ISO 8601) for auto-import window checks."""
    if not date_str:
        return None
    if isinstance(date_str, datetime):
        if date_str.tzinfo is None:
            return date_str.replace(tzinfo=timezone.utc)
        return date_str
    try:
        normalized = date_str.strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (ValueError, TypeError):
        return None


def _parse_zotero_date(date_str: str | None) -> str | None:
    if not date_str:
        return None
    try:
        s = date_str.strip()
        # ISO format: starts with YYYY-MM-DD
        iso_match = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
        if iso_match:
            return iso_match.group(1)
        # ISO partial: YYYY-MM
        if len(s) == 7 and s[4] == "-":
            return s + "-01"
        # Bare 4-digit year
        if len(s) == 4 and s.isdigit():
            return s + "-01-01"
        # Human-readable date (e.g. "August 3, 2025"): extract 4-digit year
        year_match = re.search(r"\b(\d{4})\b", s)
        if year_match:
            return year_match.group(1) + "-01-01"
    except Exception:
        pass
    return None


def _has_importable_metadata(item_data: dict[str, Any]) -> bool:
    """True if a Zotero item has enough metadata to be importable.

    An item must have at least a title, DOI, or URL — the import pipeline
    cannot do anything with an item lacking all three. Used both to skip such
    items during import and to mark them in the library modal.
    """
    return bool(
        (item_data.get("title") or "").strip()
        or (item_data.get("DOI") or "").strip()
        or (item_data.get("url") or "").strip()
    )


def _zotero_creators_to_authors(creators: list[dict[str, Any]]) -> list[str]:
    authors: list[str] = []
    for creator in creators:
        if creator.get("creatorType") not in ("author", None):
            continue
        first = (creator.get("firstName") or "").strip()
        last = (creator.get("lastName") or "").strip()
        name = (creator.get("name") or "").strip()
        if name:
            authors.append(name)
        elif first or last:
            authors.append(f"{first} {last}".strip())
    return authors


def _map_zotero_color(hex_color: str | None) -> str:
    if not hex_color:
        return "yellow"
    hex_color = hex_color.lower().lstrip("#")
    if len(hex_color) != 6:
        return "yellow"
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
    except ValueError:
        return "yellow"
    best = "yellow"
    best_dist = float("inf")
    palette = {
        "yellow": (255, 235, 59),
        "green": (76, 175, 80),
        "blue": (33, 150, 243),
        "pink": (233, 30, 99),
        "purple": (156, 39, 176),
    }
    for name, (pr, pg, pb) in palette.items():
        dist = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if dist < best_dist:
            best_dist = dist
            best = name
    return best


def _page_from_annotation(data: dict[str, Any]) -> int | None:
    """PDF page for viewer placement. Prefer pageIndex from annotationPosition over
    annotationPageLabel, which is often the journal's printed page number."""
    position_raw = data.get("annotationPosition")
    if position_raw:
        try:
            position = (
                json.loads(position_raw)
                if isinstance(position_raw, str)
                else position_raw
            )
            page_index = position.get("pageIndex")
            if page_index is not None:
                return int(page_index) + 1
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    page_label = data.get("annotationPageLabel")
    if page_label:
        try:
            return int(str(page_label).strip())
        except ValueError:
            pass
    return None


def _convert_zotero_position(ann_data: dict[str, Any]) -> dict[str, Any] | None:
    """
    Convert a Zotero annotationPosition (PDF-point coordinate space) into the
    ScaledPosition dict that react-pdf-highlighter-extended consumes.

    Zotero format:
        { "pageIndex": 0, "rects": [[x1,y1,x2,y2], ...] }  (y=0 at bottom)

    ScaledPosition format (usePdfCoordinates=true lets the viewer handle the
    y-axis flip internally):
        {
          "boundingRect": {"x1":…,"y1":…,"x2":…,"y2":…,"width":…,"height":…,"pageNumber":1},
          "rects": [...same shape...],
          "usePdfCoordinates": true
        }

    Page width/height (required by the viewer) are read from the _page_width /
    _page_height keys that import_batch embeds in each annotation dict.
    """
    pos_raw = ann_data.get("annotationPosition")
    if not pos_raw:
        return None
    try:
        position = json.loads(pos_raw) if isinstance(pos_raw, str) else pos_raw
    except (json.JSONDecodeError, TypeError):
        return None

    page_index = position.get("pageIndex", 0)
    page_number = page_index + 1
    raw_rects = position.get("rects") or []
    if not raw_rects:
        return None

    page_w = float(ann_data.get("_page_width") or 0)
    page_h = float(ann_data.get("_page_height") or 0)

    rects: list[dict[str, Any]] = []
    for r in raw_rects:
        try:
            if isinstance(r, (list, tuple)) and len(r) >= 4:
                x1, y1, x2, y2 = float(r[0]), float(r[1]), float(r[2]), float(r[3])
            elif isinstance(r, dict):
                x1 = float(r.get("x", r.get("x1", 0)) or 0)
                y1 = float(r.get("y", r.get("y1", 0)) or 0)
                x2 = (
                    x1 + float(r.get("width", 0))
                    if "width" in r
                    else float(r.get("x2", 0))
                )
                y2 = (
                    y1 + float(r.get("height", 0))
                    if "height" in r
                    else float(r.get("y2", 0))
                )
            else:
                continue
        except (TypeError, ValueError):
            continue
        rects.append(
            {
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "width": page_w,
                "height": page_h,
                "pageNumber": page_number,
            }
        )

    if not rects:
        return None

    bounding = {
        "x1": min(r["x1"] for r in rects),
        "y1": min(r["y1"] for r in rects),
        "x2": max(r["x2"] for r in rects),
        "y2": max(r["y2"] for r in rects),
        "width": page_w,
        "height": page_h,
        "pageNumber": page_number,
    }
    return {"boundingRect": bounding, "rects": rects, "usePdfCoordinates": True}


def _serialize_annotations_payload(
    annotations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {"key": ann.get("key", ""), "data": ann.get("data", {})}
        for ann in annotations
        if ann.get("key")
    ]


def _normalize_payload_item(
    item: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(item, dict):
        return None
    if "data" in item and item.get("key"):
        data = item.get("data")
        if isinstance(data, dict):
            return str(item["key"]), data
    if item.get("annotationType") is not None or item.get("annotationText") is not None:
        key = item.get("key") or item.get("annotationKey")
        if key:
            return str(key), item
    return None


def _embed_page_dims_in_annotation_data(
    ann_data: dict[str, Any],
    page_dims: dict[int, tuple[float, float]],
) -> None:
    pos_raw = ann_data.get("annotationPosition")
    if not pos_raw:
        return
    try:
        pos = json.loads(pos_raw) if isinstance(pos_raw, str) else pos_raw
        idx = pos.get("pageIndex", 0)
    except (json.JSONDecodeError, TypeError, AttributeError):
        idx = 0
    w, h = page_dims.get(idx, (0.0, 0.0))
    ann_data["_page_width"] = w
    ann_data["_page_height"] = h


def _get_page_dims_for_paper(paper: Document) -> dict[int, tuple[float, float]]:
    if not paper.s3_object_key:
        return {}
    try:
        pdf_bytes = s3_service.download_bytes(str(paper.s3_object_key))
        return extract_pdf_page_dimensions(pdf_bytes)
    except Exception as e:
        logger.warning(
            "Failed to download PDF for page dimensions (paper %s): %s",
            paper.id,
            e,
        )
        return {}


def _apply_single_zotero_annotation(
    db: Session,
    *,
    paper_id: UUID,
    user: CurrentUser,
    zotero_annotation_key: str,
    ann_data: dict[str, Any],
    raw_content: str,
    page_offsets: dict[int, tuple[int, int]] | None,
) -> bool:
    """Create a highlight (+ optional comment) for one Zotero annotation. Returns True if created."""
    ann_type = (ann_data.get("annotationType") or "highlight").lower()

    if ann_type == "ink":
        return False

    raw_text = (ann_data.get("annotationText") or "").strip()
    comment = (ann_data.get("annotationComment") or "").strip()

    is_text_annotation = ann_type in ("highlight", "underline")
    if ann_type == "note":
        if not comment:
            return False
        raw_text = ""
    elif ann_type == "image":
        raw_text = ""
    elif is_text_annotation and not raw_text and not comment:
        return False

    start_offset: int | None = None
    end_offset: int | None = None
    if raw_text and raw_content:
        so, eo = find_offsets(raw_text, raw_content)
        if so >= 0 and eo >= 0:
            start_offset = so
            end_offset = eo

    page_number = _page_from_annotation(ann_data)
    if page_number is None and start_offset is not None and page_offsets:
        from app.helpers.parser import get_start_page_from_offset

        page_number = get_start_page_from_offset(page_offsets, start_offset)

    position = _convert_zotero_position(ann_data)

    item = research_repository.create_highlight_thread(
        db,
        document_id=paper_id,
        user_id=user.id,
        create=HighlightThreadCreate(
            quote_text=raw_text,
            start_offset=start_offset,
            end_offset=end_offset,
            page_number=page_number,
            position=position,
            color=_map_zotero_color(ann_data.get("annotationColor")),
            is_shared=True,
            role=RoleType.USER.value,
            zotero_annotation_key=zotero_annotation_key,
        ),
    )

    if comment:
        research_repository.add_comment(
            db,
            thread_id=item.id,
            user_id=user.id,
            content=comment,
            role=RoleType.USER.value,
        )
    return True


def _try_backfill_or_apply_annotation(
    db: Session,
    *,
    paper_id: UUID,
    user: CurrentUser,
    zotero_annotation_key: str,
    ann_data: dict[str, Any],
    raw_content: str,
    page_offsets: dict[int, tuple[int, int]] | None,
) -> bool:
    """
    Backfill an existing highlight's Zotero key when possible; otherwise create a new one.
    Returns True when a key was backfilled or a new highlight was created.
    """
    ann_type = (ann_data.get("annotationType") or "highlight").lower()
    if ann_type == "ink":
        return False

    raw_text = (ann_data.get("annotationText") or "").strip()
    comment = (ann_data.get("annotationComment") or "").strip()
    if ann_type == "note":
        if not comment:
            return False
        raw_text = ""
    elif ann_type == "image":
        raw_text = ""
    elif ann_type in ("highlight", "underline") and not raw_text and not comment:
        return False

    page_number = _page_from_annotation(ann_data)
    candidate = research_repository.find_zotero_backfill_candidate(
        db,
        document_id=paper_id,
        user_id=user.id,
        quote_text=raw_text,
        page_number=page_number,
    )
    if candidate:
        research_repository.set_zotero_annotation_key(
            db,
            thread=candidate,
            zotero_annotation_key=zotero_annotation_key,
        )
        return True

    return _apply_single_zotero_annotation(
        db,
        paper_id=paper_id,
        user=user,
        zotero_annotation_key=zotero_annotation_key,
        ann_data=ann_data,
        raw_content=raw_content,
        page_offsets=page_offsets,
    )


async def _resolve_pdf_bytes(
    client: ZoteroApiClient,
    item: dict[str, Any],
) -> tuple[
    bytes | None,
    str,
    str | None,
    str | None,
    list[dict[str, Any]],
    str | None,
]:
    """
    Returns (pdf_bytes, import_source, attachment_key, source_url, annotations, failure_reason).
    failure_reason is set when pdf_bytes is None, describing why the PDF could not be retrieved.
    """
    item_key = item.get("key", "")
    data = item.get("data", {})
    children = await asyncio.to_thread(client.get_children, item_key)
    pdf_attachment = client.find_pdf_attachment(children)

    failure_reason: str | None = None

    if pdf_attachment:
        attachment_key = pdf_attachment.get("key", "")
        link_mode = (pdf_attachment.get("data", {}).get("linkMode") or "").lower()
        if link_mode == "linked_file":
            failure_reason = (
                "PDF is a linked local file and cannot be accessed via the Zotero API. "
                'In Zotero, right-click the attachment and choose "Store Copy of File".'
            )
        elif link_mode == "linked_url":
            failure_reason = (
                "PDF is a linked URL (e.g. a paywalled journal page) and cannot be downloaded directly. "
                "In Zotero, attach the PDF file itself instead of a URL."
            )
        else:
            try:
                pdf_bytes = await asyncio.to_thread(
                    client.download_attachment_file, attachment_key
                )
                is_valid, err = await asyncio.to_thread(
                    validate_pdf_content,
                    pdf_bytes,
                    "zotero",
                )
                if is_valid:
                    attachment_children = await asyncio.to_thread(
                        client.get_children, attachment_key
                    )
                    annotations = client.get_annotations_for_attachment(
                        attachment_children
                    )
                    return (
                        pdf_bytes,
                        ZoteroImportSource.PDF_ATTACHMENT,
                        attachment_key,
                        None,
                        annotations,
                        None,
                    )
                logger.warning(
                    "Zotero PDF attachment invalid for %s: %s", item_key, err
                )
                failure_reason = f"PDF attachment could not be validated: {err}"
            except Exception as e:
                logger.warning(
                    "Failed to download Zotero PDF for %s: %s",
                    item_key,
                    e,
                    exc_info=True,
                )
                failure_reason = "PDF attachment download failed."
    else:
        failure_reason = "No PDF attached to this item in Zotero."

    urls = list(client.resolve_item_urls(data))
    for url in urls:
        is_valid, pdf_bytes, err = await asyncio.to_thread(
            validate_url_and_fetch_pdf,
            url,
        )
        if is_valid and pdf_bytes:
            return pdf_bytes, ZoteroImportSource.URL, None, url, [], None

    if urls:
        failure_reason = (
            "Could not download a PDF from the item's URL. "
            "The page may require authentication or does not link to a PDF directly."
        )

    return None, ZoteroImportSource.URL, None, None, [], failure_reason


def _resolve_zotero_attachment_info(
    client: ZoteroApiClient,
    item: dict[str, Any],
) -> tuple[str, str | None, str | None, list[dict[str, Any]]]:
    """Return attachment metadata and annotations without downloading the PDF."""
    item_key = item.get("key", "")
    data = item.get("data", {})
    children = client.get_children(item_key)
    pdf_attachment = client.find_pdf_attachment(children)

    if pdf_attachment:
        attachment_key = pdf_attachment.get("key", "")
        attachment_children = client.get_children(attachment_key)
        annotations = client.get_annotations_for_attachment(attachment_children)
        return (
            ZoteroImportSource.PDF_ATTACHMENT,
            attachment_key or None,
            None,
            annotations,
        )

    urls = client.resolve_item_urls(data)
    source_url = urls[0] if urls else None
    return ZoteroImportSource.URL, None, source_url, []


async def _link_zotero_item_to_existing_paper(
    db: Session,
    *,
    client: ZoteroApiClient,
    item: dict[str, Any],
    item_key: str,
    paper: Document,
    user: CurrentUser,
) -> None:
    """Link a Zotero item to an existing paper and merge any new annotations."""
    import_source, attachment_key, source_url, annotations = (
        _resolve_zotero_attachment_info(client, item)
    )
    annotation_payload = (
        _serialize_annotations_payload(annotations) if annotations else None
    )

    import_row = zotero_import_crud.create(
        db,
        user_id=user.id,
        zotero_item_key=item_key,
        import_source=import_source,
        zotero_attachment_key=attachment_key,
        source_url=source_url,
        paper_id=UUID(str(paper.id)),
        annotations_payload=annotation_payload,
        status=ZoteroImportStatus.COMPLETED,
    )

    if (
        import_source == ZoteroImportSource.PDF_ATTACHMENT
        and attachment_key
        and annotations
    ):
        _sync_item(db, client=client, import_row=import_row, user=user)


def _apply_zotero_tags(
    db: Session,
    *,
    paper_id: UUID,
    tags_data: list[dict[str, Any]],
    user: "CurrentUser",
) -> None:
    for tag_entry in tags_data:
        if not isinstance(tag_entry, dict):
            continue
        tag_name = (tag_entry.get("tag") or "").strip()
        if not tag_name:
            continue
        tag = library_tag_repository.get_or_create(
            db,
            user_id=user.id,
            name=tag_name,
        )
        library_tag_repository.assign_to_document(
            db,
            user_id=user.id,
            document_id=paper_id,
            tag_id=tag.id,
        )


def _compute_max_new_imports(
    db: Session, user: CurrentUser, limit: int
) -> tuple[int, str | None]:
    """Return how many new papers can be imported and an error if at upload limit."""
    can_upload, upload_err = can_user_upload_paper(db, user)
    if not can_upload:
        return 0, upload_err

    remaining = get_remaining_paper_upload_slots(db, user)
    return min(limit, remaining), None


async def _discover_import_candidates(
    db: Session,
    *,
    client: ZoteroApiClient,
    user: CurrentUser,
    limit: int,
) -> tuple[
    list[dict[str, Any]],
    list[tuple[dict[str, Any], str, str]],
    int,
    list[dict[str, str]],
]:
    """
    Sequential scan of Zotero items: skip/link/dedup, then collect import candidates.

    Returns (candidates, deferred_links, skipped_already_imported, errors).
    deferred_links entries are (item, item_key, first_item_key_in_batch).
    """
    candidates: list[dict[str, Any]] = []
    deferred_links: list[tuple[dict[str, Any], str, str]] = []
    errors: list[dict[str, str]] = []
    skipped_already_imported = 0
    batch_doi_claimed: dict[str, str] = {}
    start = 0
    page_size = 25
    upload_limit_hit = False

    max_new, upload_err = _compute_max_new_imports(db, user, limit)

    while len(candidates) < max_new and not upload_limit_hit:
        items = client.get_top_importable_items(limit=page_size, start=start)
        if not items:
            break
        start += page_size

        for item in items:
            if len(candidates) >= max_new:
                break

            item_key = item.get("key", "")
            if not item_key:
                continue

            item_data = item.get("data", {})
            if not _has_importable_metadata(item_data):
                logger.debug("Skipping Zotero item %s: no title, DOI, or URL", item_key)
                continue

            existing_import = zotero_import_crud.get_by_item_key(
                db, user_id=user.id, zotero_item_key=item_key
            )
            if existing_import:
                paper_still_exists = False
                if existing_import.paper_id:
                    linked_paper = document_repository.find_accessible(
                        db,
                        document_id=str(existing_import.paper_id),
                        user=user,
                    )
                    paper_still_exists = bool(linked_paper)

                if (
                    existing_import.status == ZoteroImportStatus.COMPLETED
                    and paper_still_exists
                ):
                    skipped_already_imported += 1
                    continue

                db.delete(existing_import)
                db.commit()

            doi = normalize_doi(item_data.get("DOI"))
            if doi:
                target_paper = document_repository.find_library_document_by_doi(
                    db, user_id=user.id, doi=doi
                )
                if target_paper:
                    await _link_zotero_item_to_existing_paper(
                        db,
                        client=client,
                        item=item,
                        item_key=item_key,
                        paper=target_paper,
                        user=user,
                    )
                    skipped_already_imported += 1
                    continue

                if doi in batch_doi_claimed:
                    deferred_links.append((item, item_key, batch_doi_claimed[doi]))
                    skipped_already_imported += 1
                    continue

            if len(candidates) >= max_new:
                if max_new == 0 and upload_err:
                    errors.append(
                        {
                            "zotero_item_key": item_key,
                            "error": upload_err or "Upload limit",
                        }
                    )
                    upload_limit_hit = True
                break

            if max_new == 0:
                errors.append(
                    {
                        "zotero_item_key": item_key,
                        "error": upload_err or "Upload limit",
                    }
                )
                upload_limit_hit = True
                break

            if doi:
                batch_doi_claimed[doi] = item_key

            candidates.append(item)

        if len(items) < page_size:
            break

    return candidates, deferred_links, skipped_already_imported, errors


def _apply_metadata_from_zotero(
    db: Session,
    *,
    paper: Document,
    item_data: dict[str, Any],
    user: CurrentUser,
) -> None:
    """
    Apply Zotero's authoritative metadata (title, authors, abstract, publish
    date, DOI) to a paper. Zotero is the source of truth for these fields, so the
    jobs worker skips LLM extraction and the webhook never overwrites them.
    """
    authors = _zotero_creators_to_authors(item_data.get("creators") or [])
    publish_date = _parse_zotero_date(item_data.get("date"))
    document_repository.update_canonical(
        db,
        document=paper,
        update=DocumentUpdate(
            title=item_data.get("title") or None,
            authors=authors or None,
            abstract=item_data.get("abstractNote") or None,
            publish_date=publish_date,
            doi=item_data.get("DOI") or None,
        ),
        user=user,
    )


async def _import_one_paper(
    item: dict[str, Any],
    *,
    user: CurrentUser,
    zotero_user_id: str,
    api_key: str,
) -> ImportOneResult:
    """
    Submit a single Zotero item to the PDF jobs service for lightweight processing.

    Zotero already supplies authoritative metadata, so we upload the PDF, create
    the paper with that metadata, and hand off to the jobs worker (with LLM
    metadata extraction skipped) to fill in the deterministic outputs (preview,
    raw text, page offsets). The paper-processing webhook finalizes the import
    and applies Zotero annotations once the worker completes. Returns status
    "processing" on successful submission.
    """
    item_key = item.get("key", "")
    db = SessionLocal()
    client = ZoteroApiClient(zotero_user_id=zotero_user_id, api_key=api_key)
    upload_job_id: str | None = None
    import_row: ZoteroImportedItem | None = None
    created_paper_id: str | None = None

    try:
        import_row = zotero_import_crud.create(
            db,
            user_id=user.id,
            zotero_item_key=item_key,
            import_source=ZoteroImportSource.PDF_ATTACHMENT,
            status=ZoteroImportStatus.PROCESSING,
        )

        (
            pdf_bytes,
            import_source,
            attachment_key,
            source_url,
            annotations,
            failure_reason,
        ) = await _resolve_pdf_bytes(client, item)
        if not pdf_bytes:
            if import_row:
                zotero_import_crud.update_status(
                    db,
                    item=import_row,
                    status=ZoteroImportStatus.FAILED,
                    error_message=failure_reason
                    or "No PDF available from attachment or URL",
                )
            return {
                "status": "error",
                "zotero_item_key": item_key,
                "error": failure_reason or "No PDF available from attachment or URL",
            }

        safe_filename = f"zotero-{item_key}.pdf"
        paper_upload_job = reserve_upload(
            db,
            requester=user,
            project_id=None,
            input_size_bytes=len(pdf_bytes),
            original_filename=safe_filename,
            content_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
        )
        upload_job_id = str(paper_upload_job.id)
        task_id = await submit_reserved_document(
            pdf_bytes=pdf_bytes,
            upload_job=paper_upload_job,
            db=db,
            user=user,
            skip_metadata_extraction=True,
        )

        data = item.get("data", {})
        paper = document_repository.find_by_upload_job(
            db=db,
            upload_job_id=upload_job_id,
            user=user,
        )
        if paper is None:
            raise RuntimeError("zotero_canonical_document_missing")

        paper_id = UUID(str(paper.id))
        created_paper_id = str(paper.id)

        _apply_metadata_from_zotero(db, paper=paper, item_data=data, user=user)
        _apply_zotero_tags(
            db,
            paper_id=paper_id,
            tags_data=data.get("tags") or [],
            user=user,
        )

        annotation_payload = (
            _serialize_annotations_payload(annotations) if annotations else None
        )

        # Finalize the import row BEFORE submitting the job so the webhook
        # recognizes this as a Zotero import (and keeps the paper instead of
        # requiring LLM metadata) even if the worker completes immediately.
        if import_row:
            zotero_import_crud.finalize_processing_import(
                db,
                item=import_row,
                import_source=import_source,
                zotero_attachment_key=attachment_key,
                source_url=source_url,
                paper_id=paper_id,
                upload_job_id=UUID(upload_job_id),
                annotations_payload=annotation_payload,
            )

        if task_id.startswith("reused:"):
            apply_zotero_annotations(
                db=db,
                upload_job_id=upload_job_id,
                paper_id=str(paper.id),
                user=user,
            )

        return {
            "status": "processing",
            "zotero_item_key": item_key,
            "paper_id": str(paper_id),
            "upload_job_id": upload_job_id,
            "import_source": import_source,
            "title": data.get("title"),
            "imported_via_url": import_source == ZoteroImportSource.URL,
        }
    except Exception as e:
        logger.error(
            "Zotero import failed for item %s: %s",
            item_key,
            e,
            exc_info=True,
        )
        if import_row:
            zotero_import_crud.update_status(
                db,
                item=import_row,
                status=ZoteroImportStatus.FAILED,
                error_message=str(e),
            )
        # Remove the paper created before the failed hand-off so we don't leave
        # an orphan with no content (the import row's FK is ON DELETE SET NULL).
        if created_paper_id:
            try:
                entry = document_repository.require_library_paper_by_document(
                    db,
                    document_id=UUID(str(created_paper_id)),
                    user_id=user.id,
                )
                document_repository.delete_library_paper(
                    db,
                    library_paper_id=entry.id,
                    user_id=user.id,
                )
            except Exception as cleanup_err:
                logger.warning(
                    "Failed to clean up paper %s after Zotero import error: %s",
                    created_paper_id,
                    cleanup_err,
                )
        if upload_job_id:
            upload_reservation_repository.mark_as_failed(
                db=db, job_id=upload_job_id, user=user
            )
        return {
            "status": "error",
            "zotero_item_key": item_key,
            "error": "zotero_import_failed",
        }
    finally:
        db.close()


def list_library(
    db: Session,
    *,
    user: CurrentUser,
    limit: int = 100,
) -> dict[str, Any]:
    """
    Fetch and annotate importable items from the user's Zotero library.

    Returns up to `limit` items sorted by dateModified (Zotero default), each
    annotated with an `already_imported` flag.
    """
    connection = zotero_crud.get_by_user_id(db, user_id=user.id)
    if not connection:
        raise ValueError("Zotero account not connected")

    client = ZoteroApiClient(
        zotero_user_id=str(connection.zotero_user_id),
        api_key=str(connection.api_key),
    )

    items: list[dict[str, Any]] = []
    page_size = 25
    start = 0
    while len(items) < limit:
        batch = client.get_top_importable_items(limit=page_size, start=start)
        if not batch:
            break
        items.extend(batch[: limit - len(items)])
        if len(batch) < page_size:
            break
        start += page_size

    imported_keys = set(
        db.scalars(
            select(ZoteroImportedItem.zotero_item_key)
            .join(Document, ZoteroImportedItem.paper_id == Document.id)
            .where(
                ZoteroImportedItem.user_id == user.id,
                ZoteroImportedItem.status == ZoteroImportStatus.COMPLETED,
                ZoteroImportedItem.paper_id.isnot(None),
            )
        ).all()
    )

    # Determine which top-level items have a stored PDF attachment so the modal
    # can surface only the papers the import pipeline can actually download a PDF
    # for (the same stored-PDF predicate find_pdf_attachment uses at import time).
    # A single bulk attachment scan avoids a per-item children call.
    pdf_parent_keys: set[str] = client.get_pdf_parent_item_keys()

    # Map collection keys -> names so the modal can offer a collection filter.
    collection_names: dict[str, str] = client.get_collections()

    result = []
    for item in items:
        data = item.get("data", {})
        item_key = item.get("key", "")
        creators = data.get("creators") or []
        authors: list[str] = []
        for c in creators:
            if c.get("creatorType") not in ("author", None):
                continue
            first = (c.get("firstName") or "").strip()
            last = (c.get("lastName") or "").strip()
            name = (c.get("name") or "").strip()
            if name:
                authors.append(name)
            elif first or last:
                authors.append(f"{first} {last}".strip())

        item_type = data.get("itemType", "")
        venue = (
            data.get("publicationTitle")
            or data.get("proceedingsTitle")
            or data.get("conferenceName")
            or data.get("repository")
            or None
        )
        tags = [
            (t.get("tag") or "").strip()
            for t in (data.get("tags") or [])
            if (t.get("tag") or "").strip()
        ]
        collections = [
            collection_names[key]
            for key in (data.get("collections") or [])
            if key in collection_names
        ]
        result.append(
            {
                "zotero_item_key": item_key,
                "title": (data.get("title") or "").strip(),
                "authors": authors,
                "date": _parse_zotero_date(data.get("date")),
                # Raw ISO 8601 timestamp (lexically sortable) for the "date added" sort.
                "date_added": (data.get("dateAdded") or "").strip() or None,
                "item_type": item_type,
                "venue": venue,
                "tags": tags,
                "collections": collections,
                "already_imported": item_key in imported_keys,
                "has_pdf_attachment": item_key in pdf_parent_keys,
                "has_metadata": _has_importable_metadata(data),
            }
        )

    remaining = get_remaining_paper_upload_slots(db, user)
    return {"items": result, "remaining_slots": remaining}


async def _discover_candidates_by_keys(
    db: Session,
    *,
    client: ZoteroApiClient,
    user: CurrentUser,
    item_keys: list[str],
) -> tuple[
    list[dict[str, Any]],
    list[tuple[dict[str, Any], str, str]],
    int,
    list[dict[str, str]],
]:
    """
    Resolve specific Zotero item keys into import candidates.

    Mirrors the dedup/linking logic of _discover_import_candidates but targets
    only the caller-specified keys instead of scanning the full library.
    Returns (candidates, deferred_links, skipped_already_imported, errors).
    """
    candidates: list[dict[str, Any]] = []
    deferred_links: list[tuple[dict[str, Any], str, str]] = []
    errors: list[dict[str, str]] = []
    skipped_already_imported = 0
    batch_doi_claimed: dict[str, str] = {}

    max_new, upload_err = _compute_max_new_imports(db, user, len(item_keys))
    if max_new == 0:
        for key in item_keys:
            errors.append(
                {"zotero_item_key": key, "error": upload_err or "Upload limit"}
            )
        return candidates, deferred_links, skipped_already_imported, errors

    items = client.get_items_by_keys(item_keys)

    for item in items:
        if len(candidates) >= max_new:
            break

        item_key = item.get("key", "")
        if not item_key:
            continue

        item_data = item.get("data", {})
        if not _has_importable_metadata(item_data):
            continue

        existing_import = zotero_import_crud.get_by_item_key(
            db, user_id=user.id, zotero_item_key=item_key
        )
        if existing_import:
            paper_still_exists = False
            if existing_import.paper_id:
                linked_paper = document_repository.find_accessible(
                    db,
                    document_id=str(existing_import.paper_id),
                    user=user,
                )
                paper_still_exists = bool(linked_paper)

            if (
                existing_import.status == ZoteroImportStatus.COMPLETED
                and paper_still_exists
            ):
                skipped_already_imported += 1
                continue

            db.delete(existing_import)
            db.commit()

        doi = normalize_doi(item_data.get("DOI"))
        if doi:
            target_paper = document_repository.find_library_document_by_doi(
                db, user_id=user.id, doi=doi
            )
            if target_paper:
                await _link_zotero_item_to_existing_paper(
                    db,
                    client=client,
                    item=item,
                    item_key=item_key,
                    paper=target_paper,
                    user=user,
                )
                skipped_already_imported += 1
                continue

            if doi in batch_doi_claimed:
                deferred_links.append((item, item_key, batch_doi_claimed[doi]))
                skipped_already_imported += 1
                continue

        if doi:
            batch_doi_claimed[doi] = item_key

        candidates.append(item)

    return candidates, deferred_links, skipped_already_imported, errors


async def import_batch(
    db: Session,
    *,
    user: CurrentUser,
    item_keys: list[str],
) -> dict[str, Any]:
    """
    Import the specified Zotero items by key.

    Zotero already provides authoritative metadata (title, authors, abstract, DOI,
    publish date, tags, annotations), so each item is uploaded and submitted to the
    Celery jobs worker with LLM metadata extraction skipped — the worker only
    produces the deterministic outputs (preview, raw text, page offsets). Import is
    asynchronous: this returns once items are submitted ("processing"), and the
    paper-processing webhook finalizes each paper and applies Zotero annotations as
    the worker completes. Progress is tracked via the zotero_imported_items rows.
    """
    connection = zotero_crud.get_by_user_id(db, user_id=user.id)
    if not connection:
        raise ValueError("Zotero account not connected")

    client = ZoteroApiClient(
        zotero_user_id=str(connection.zotero_user_id),
        api_key=str(connection.api_key),
    )

    (
        candidates,
        deferred_links,
        skipped_already_imported,
        errors,
    ) = await _discover_candidates_by_keys(
        db, client=client, user=user, item_keys=item_keys
    )

    imported: list[dict[str, Any]] = []
    imported_via_url = 0

    if candidates:
        sem = asyncio.Semaphore(ZOTERO_IMPORT_CONCURRENCY)

        async def run_one(item: dict[str, Any]) -> ImportOneResult:
            async with sem:
                return await _import_one_paper(
                    item,
                    user=user,
                    zotero_user_id=str(connection.zotero_user_id),
                    api_key=str(connection.api_key),
                )

        raw_results = await asyncio.gather(
            *[run_one(item) for item in candidates],
            return_exceptions=True,
        )

        item_key_to_paper_id: dict[str, str] = {}
        for i, raw in enumerate(raw_results):
            if isinstance(raw, BaseException):
                item_key = candidates[i].get("key", "")
                logger.error(
                    "Unexpected Zotero import failure for %s: %s",
                    item_key,
                    raw,
                    exc_info=True,
                )
                errors.append(
                    {
                        "zotero_item_key": item_key,
                        "error": "zotero_import_failed",
                    }
                )
                continue

            if raw["status"] == "error":
                errors.append(
                    {
                        "zotero_item_key": raw["zotero_item_key"],
                        "error": raw["error"] or "Import failed",
                    }
                )
                continue

            imported.append(
                {
                    "zotero_item_key": raw["zotero_item_key"],
                    "paper_id": raw["paper_id"],
                    "upload_job_id": raw["upload_job_id"],
                    "import_source": raw["import_source"],
                    "title": raw["title"],
                }
            )
            if raw["imported_via_url"]:
                imported_via_url += 1
            item_key_to_paper_id[raw["zotero_item_key"]] = raw["paper_id"]

        for item, item_key, first_item_key in deferred_links:
            first_paper_id = item_key_to_paper_id.get(first_item_key)
            if not first_paper_id:
                continue
            paper = document_repository.find_accessible(
                db, document_id=first_paper_id, user=user
            )
            if not paper:
                continue
            await _link_zotero_item_to_existing_paper(
                db,
                client=client,
                item=item,
                item_key=item_key,
                paper=paper,
                user=user,
            )

    return {
        "imported": imported,
        "imported_count": len(imported),
        "imported_via_url": imported_via_url,
        "skipped_already_imported": skipped_already_imported,
        "errors": errors,
    }


def apply_zotero_annotations(
    db: Session,
    *,
    upload_job_id: str,
    paper_id: str,
    user: CurrentUser,
) -> None:
    import_row = zotero_import_crud.get_by_upload_job_id(
        db, upload_job_id=UUID(upload_job_id)
    )
    if not import_row:
        return

    if (
        import_row.import_source == ZoteroImportSource.URL
        or not import_row.annotations_payload
    ):
        zotero_import_crud.update_status(
            db,
            item=import_row,
            status=ZoteroImportStatus.COMPLETED,
            paper_id=UUID(paper_id),
        )
        return

    try:
        raw_file = require_parsed_content(
            db,
            document_id=UUID(paper_id),
            user=user,
        )
        raw_content = raw_file.raw_content or ""
        page_offsets = raw_file.page_offsets

        # Page dimensions are needed to convert Zotero annotation positions. The
        # stored payload no longer carries them (the worker, not the server,
        # processes the PDF), so derive them from the PDF here.
        paper = document_repository.find_accessible(db, document_id=paper_id, user=user)
        page_dims = _get_page_dims_for_paper(paper) if paper else {}

        annotations_payload = cast(
            list[dict[str, Any]], import_row.annotations_payload or []
        )
        for payload_item in annotations_payload:
            normalized = _normalize_payload_item(payload_item)
            if not normalized:
                continue
            zotero_key, ann_data = normalized
            _embed_page_dims_in_annotation_data(ann_data, page_dims)
            _apply_single_zotero_annotation(
                db,
                paper_id=UUID(paper_id),
                user=user,
                zotero_annotation_key=zotero_key,
                ann_data=ann_data,
                raw_content=raw_content,
                page_offsets=page_offsets,
            )

        zotero_import_crud.update_status(
            db,
            item=import_row,
            status=ZoteroImportStatus.COMPLETED,
            paper_id=UUID(paper_id),
        )
    except Exception as e:
        logger.error(
            "Failed to apply Zotero annotations for job %s: %s",
            upload_job_id,
            e,
            exc_info=True,
        )
        zotero_import_crud.update_status(
            db,
            item=import_row,
            status=ZoteroImportStatus.FAILED,
            error_message=str(e),
            paper_id=UUID(paper_id),
        )


def _sync_item(
    db: Session,
    *,
    client: ZoteroApiClient,
    import_row: ZoteroImportedItem,
    user: CurrentUser,
) -> dict[str, Any]:
    paper_id = import_row.paper_id
    if not paper_id or not import_row.zotero_attachment_key:
        raise ValueError("Import row is missing paper or attachment key")

    paper = document_repository.find_accessible(
        db, document_id=str(paper_id), user=user
    )
    if not paper:
        raise ValueError("Linked paper no longer exists")

    attachment_children = client.get_children(str(import_row.zotero_attachment_key))
    remote_annotations = client.get_annotations_for_attachment(attachment_children)
    existing_keys = research_repository.get_zotero_annotation_keys(
        db,
        document_id=UUID(str(paper_id)),
        user_id=user.id,
    )

    missing_annotations = [
        ann
        for ann in remote_annotations
        if ann.get("key") and ann["key"] not in existing_keys
    ]

    new_annotations_count = 0
    if missing_annotations:
        page_dims = _get_page_dims_for_paper(paper)
        raw_file = require_parsed_content(
            db,
            document_id=UUID(str(paper_id)),
            user=user,
        )
        raw_content = raw_file.raw_content or ""
        page_offsets = raw_file.page_offsets

        for ann in missing_annotations:
            zotero_key = str(ann["key"])
            ann_data = dict(ann.get("data") or {})
            _embed_page_dims_in_annotation_data(ann_data, page_dims)
            if _try_backfill_or_apply_annotation(
                db,
                paper_id=UUID(str(paper_id)),
                user=user,
                zotero_annotation_key=zotero_key,
                ann_data=ann_data,
                raw_content=raw_content,
                page_offsets=page_offsets,
            ):
                new_annotations_count += 1

    zotero_import_crud.update_after_sync(
        db,
        item=import_row,
        annotations_payload=_serialize_annotations_payload(remote_annotations),
        last_synced_at=datetime.now(timezone.utc),
    )

    return {
        "zotero_item_key": import_row.zotero_item_key,
        "paper_id": str(paper_id),
        "new_annotations_count": new_annotations_count,
    }


async def sync_batch(
    db: Session,
    *,
    user: CurrentUser,
    limit: int = 50,
) -> dict[str, Any]:
    """Append-only sync of new Zotero annotations for already-imported PDF papers."""
    connection = zotero_crud.get_by_user_id(db, user_id=user.id)
    if not connection:
        raise ValueError("Zotero account not connected")

    client = ZoteroApiClient(
        zotero_user_id=str(connection.zotero_user_id),
        api_key=str(connection.api_key),
    )

    syncable = zotero_import_crud.list_syncable_by_user(
        db, user_id=user.id, limit=limit
    )

    synced: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    new_annotations_count = 0

    for import_row in syncable:
        try:
            result = _sync_item(db, client=client, import_row=import_row, user=user)
            synced.append(result)
            new_annotations_count += result["new_annotations_count"]
        except Exception as e:
            logger.error(
                "Zotero sync failed for item %s: %s",
                import_row.zotero_item_key,
                e,
                exc_info=True,
            )
            errors.append(
                {
                    "zotero_item_key": str(import_row.zotero_item_key),
                    "error": "zotero_sync_failed",
                }
            )

    unique_paper_ids = {r["paper_id"] for r in synced if r.get("paper_id")}

    return {
        "synced": synced,
        "synced_papers_count": len(unique_paper_ids),
        "synced_zotero_items_count": len(synced),
        "new_annotations_count": new_annotations_count,
        "errors": errors,
    }


async def auto_import_new_papers(
    db: Session,
    *,
    user: CurrentUser,
) -> dict[str, Any]:
    """
    For Researcher-plan users: detect Zotero library items not yet tracked in
    zotero_imported_items and import them automatically, subject to the user's
    remaining paper upload slots.

    Only items with Zotero dateAdded >= max(created_at) on completed
    zotero_imported_items are considered (first manual import batch).
    """
    connection = zotero_crud.get_by_user_id(db, user_id=user.id)
    if not connection:
        raise ValueError("Zotero account not connected")

    import_since = zotero_import_crud.get_auto_import_since(db, user_id=user.id)
    if import_since is None:
        logger.info(
            "auto_import_new_papers: no completed imports for user %s, skipping",
            user.id,
        )
        return {"auto_imported_count": 0, "skipped_limit_reached": False}

    library = list_library(db, user=user, limit=100)
    candidate_items = [
        item for item in library["items"] if not item["already_imported"]
    ]
    new_keys = []
    for item in candidate_items:
        # date_added is a raw Zotero ISO-8601 string; import_since is a tz-aware
        # datetime. Parse before comparing, or the comparison raises TypeError.
        date_added = _parse_zotero_date_added(item.get("date_added"))
        if date_added is None:
            continue
        if date_added < import_since:
            continue
        new_keys.append(item["zotero_item_key"])

    if not new_keys:
        return {"auto_imported_count": 0, "skipped_limit_reached": False}

    can_upload, _ = can_user_upload_paper(db, user)
    if not can_upload:
        logger.info(
            "auto_import_new_papers: upload limit reached for user %s, skipping %d items",
            user.id,
            len(new_keys),
        )
        return {"auto_imported_count": 0, "skipped_limit_reached": True}

    remaining = get_remaining_paper_upload_slots(db, user)
    keys_to_import = new_keys[:remaining]

    if not keys_to_import:
        return {"auto_imported_count": 0, "skipped_limit_reached": True}

    result = await import_batch(db, user=user, item_keys=keys_to_import)
    return {
        "auto_imported_count": result.get("imported_count", 0),
        "skipped_limit_reached": len(new_keys) > len(keys_to_import),
    }
