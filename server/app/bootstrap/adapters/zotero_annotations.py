"""Database-only application of Zotero annotation snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.bootstrap.adapters.research_annotations import require_parsed_content
from app.bootstrap.adapters.research_repository import (
    HighlightThreadCreate,
    research_repository,
)
from app.database.models import RoleType, ZoteroImportSource, ZoteroImportStatus
from app.llm.utils import find_offsets
from app.modules.integrations.zotero.infrastructure.import_repository import (
    zotero_import_repository,
)
from app.shared.application import Actor
from sqlalchemy.orm import Session

type PageDimensions = tuple[tuple[int, float, float], ...]


@dataclass(frozen=True, slots=True)
class ZoteroAnnotationApplyResult:
    imported_item_id: UUID
    new_annotations_count: int
    status_changed: bool


def _map_color(hex_color: str | None) -> str:
    if not hex_color:
        return "yellow"
    normalized = hex_color.lower().lstrip("#")
    if len(normalized) != 6:
        return "yellow"
    try:
        red = int(normalized[0:2], 16)
        green = int(normalized[2:4], 16)
        blue = int(normalized[4:6], 16)
    except ValueError:
        return "yellow"
    palette = {
        "yellow": (255, 235, 59),
        "green": (76, 175, 80),
        "blue": (33, 150, 243),
        "pink": (233, 30, 99),
        "purple": (156, 39, 176),
    }
    return min(
        palette,
        key=lambda name: sum(
            component**2
            for component in (
                red - palette[name][0],
                green - palette[name][1],
                blue - palette[name][2],
            )
        ),
    )


def _page_number(data: dict[str, Any]) -> int | None:
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
        except (AttributeError, json.JSONDecodeError, TypeError, ValueError):
            pass
    page_label = data.get("annotationPageLabel")
    if page_label:
        try:
            return int(str(page_label).strip())
        except ValueError:
            pass
    return None


def _position(
    data: dict[str, Any],
    *,
    page_dimensions: dict[int, tuple[float, float]],
) -> dict[str, Any] | None:
    position_raw = data.get("annotationPosition")
    if not position_raw:
        return None
    try:
        position = (
            json.loads(position_raw) if isinstance(position_raw, str) else position_raw
        )
        page_index = int(position.get("pageIndex", 0))
        raw_rects = position.get("rects") or []
    except (AttributeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not raw_rects:
        return None

    page_number = page_index + 1
    page_width, page_height = page_dimensions.get(page_index, (0.0, 0.0))
    rects: list[dict[str, float | int]] = []
    for raw_rect in raw_rects:
        try:
            if isinstance(raw_rect, (list, tuple)) and len(raw_rect) >= 4:
                x1, y1, x2, y2 = (
                    float(raw_rect[0]),
                    float(raw_rect[1]),
                    float(raw_rect[2]),
                    float(raw_rect[3]),
                )
            elif isinstance(raw_rect, dict):
                x1 = float(raw_rect.get("x", raw_rect.get("x1", 0)) or 0)
                y1 = float(raw_rect.get("y", raw_rect.get("y1", 0)) or 0)
                x2 = (
                    x1 + float(raw_rect.get("width", 0))
                    if "width" in raw_rect
                    else float(raw_rect.get("x2", 0))
                )
                y2 = (
                    y1 + float(raw_rect.get("height", 0))
                    if "height" in raw_rect
                    else float(raw_rect.get("y2", 0))
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
                "width": page_width,
                "height": page_height,
                "pageNumber": page_number,
            }
        )
    if not rects:
        return None
    bounding = {
        "x1": min(rect["x1"] for rect in rects),
        "y1": min(rect["y1"] for rect in rects),
        "x2": max(rect["x2"] for rect in rects),
        "y2": max(rect["y2"] for rect in rects),
        "width": page_width,
        "height": page_height,
        "pageNumber": page_number,
    }
    return {
        "boundingRect": bounding,
        "rects": rects,
        "usePdfCoordinates": True,
    }


def _normalized_annotation(
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    key = payload.get("key") or payload.get("annotationKey")
    data = payload.get("data", payload)
    if not key or not isinstance(data, dict):
        return None
    return str(key), data


def apply_annotation_snapshot(
    db: Session,
    *,
    document_id: UUID,
    user: Actor,
    annotations_payload: list[dict[str, Any]],
    page_dimensions: PageDimensions,
) -> int:
    """Apply missing annotations without committing or performing external I/O."""
    raw_file = require_parsed_content(
        db,
        document_id=document_id,
        user=user,
    )
    raw_content = raw_file.raw_content or ""
    page_offsets = raw_file.page_offsets
    dimensions = {
        page_index: (width, height) for page_index, width, height in page_dimensions
    }
    existing_keys = research_repository.get_zotero_annotation_keys(
        db,
        document_id=document_id,
        user_id=user.id,
    )
    applied = 0
    for payload in annotations_payload:
        normalized = _normalized_annotation(payload)
        if normalized is None:
            continue
        zotero_key, data = normalized
        if zotero_key in existing_keys:
            continue
        annotation_type = str(data.get("annotationType") or "highlight").lower()
        if annotation_type == "ink":
            continue
        quote_text = str(data.get("annotationText") or "").strip()
        comment = str(data.get("annotationComment") or "").strip()
        if annotation_type == "note":
            if not comment:
                continue
            quote_text = ""
        elif annotation_type == "image":
            quote_text = ""
        elif (
            annotation_type in {"highlight", "underline"}
            and not quote_text
            and not comment
        ):
            continue

        page_number = _page_number(data)
        candidate = research_repository.find_zotero_backfill_candidate(
            db,
            document_id=document_id,
            user_id=user.id,
            quote_text=quote_text,
            page_number=page_number,
        )
        if candidate is not None:
            research_repository.set_zotero_annotation_key(
                db,
                thread=candidate,
                zotero_annotation_key=zotero_key,
            )
            existing_keys.add(zotero_key)
            applied += 1
            continue

        start_offset: int | None = None
        end_offset: int | None = None
        if quote_text and raw_content:
            start, end = find_offsets(quote_text, raw_content)
            if start >= 0 and end >= 0:
                start_offset = start
                end_offset = end
        if page_number is None and start_offset is not None and page_offsets:
            from app.helpers.parser import get_start_page_from_offset

            page_number = get_start_page_from_offset(page_offsets, start_offset)

        thread = research_repository.create_highlight_thread(
            db,
            document_id=document_id,
            user_id=user.id,
            create=HighlightThreadCreate(
                quote_text=quote_text,
                start_offset=start_offset,
                end_offset=end_offset,
                page_number=page_number,
                position=_position(data, page_dimensions=dimensions),
                color=_map_color(
                    str(data["annotationColor"])
                    if data.get("annotationColor") is not None
                    else None
                ),
                is_shared=True,
                content_role=RoleType.USER,
                zotero_annotation_key=zotero_key,
            ),
        )
        if comment:
            research_repository.add_comment(
                db,
                thread_id=thread.id,
                user_id=user.id,
                content=comment,
                content_role=RoleType.USER,
            )
        existing_keys.add(zotero_key)
        applied += 1
    return applied


def apply_persisted_zotero_annotations(
    db: Session,
    *,
    upload_job_id: UUID,
    document_id: UUID,
    user: Actor,
    page_dimensions: PageDimensions,
) -> ZoteroAnnotationApplyResult | None:
    """Finalize one persisted Zotero import inside the caller-owned UoW."""
    imported_item = zotero_import_repository.get_by_upload_job_id(
        db,
        upload_job_id=upload_job_id,
    )
    if imported_item is None:
        return None

    applied = 0
    if (
        imported_item.import_source != ZoteroImportSource.URL
        and imported_item.annotations_payload
    ):
        applied = apply_annotation_snapshot(
            db,
            document_id=document_id,
            user=user,
            annotations_payload=list(imported_item.annotations_payload),
            page_dimensions=page_dimensions,
        )
    status_change = zotero_import_repository.update_status(
        db,
        item=imported_item,
        status=ZoteroImportStatus.COMPLETED,
        document_id=document_id,
    )
    return ZoteroAnnotationApplyResult(
        imported_item_id=imported_item.id,
        new_annotations_count=applied,
        status_changed=status_change.changed,
    )


__all__ = [
    "PageDimensions",
    "ZoteroAnnotationApplyResult",
    "apply_annotation_snapshot",
    "apply_persisted_zotero_annotations",
]
