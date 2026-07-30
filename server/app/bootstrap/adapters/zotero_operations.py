"""External-only Zotero provider and object-storage operations."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any

from app.database.telemetry import track_event
from app.helpers.parser import (
    extract_pdf_page_dimensions,
    validate_pdf_content,
    validate_url_and_fetch_pdf,
)
from app.helpers.s3 import s3_service
from app.modules.integrations.zotero.application.zotero import (
    PageDimensions,
    PreparedZoteroCallback,
    ZoteroAccessToken,
    ZoteroAttachmentSnapshot,
    ZoteroCredentials,
    ZoteroImportContent,
    ZoteroItemSnapshot,
    ZoteroLibrarySnapshot,
    ZoteroRequestToken,
    ZoteroSyncBatch,
    ZoteroSyncTarget,
    ZoteroSyncUpdate,
)
from app.modules.integrations.zotero.infrastructure.client import ZoteroApiClient
from app.modules.integrations.zotero.infrastructure.oauth import zotero_auth_client
from app.shared.application import Actor
from app.database.models import ZoteroImportSource


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip()
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", normalized)
    if match:
        return match.group(1)
    if len(normalized) == 7 and normalized[4] == "-":
        return normalized + "-01"
    if len(normalized) == 4 and normalized.isdigit():
        return normalized + "-01-01"
    match = re.search(r"\b(\d{4})\b", normalized)
    return match.group(1) + "-01-01" if match else None


def _parse_added(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)


def _authors(creators: list[dict[str, Any]]) -> tuple[str, ...]:
    result: list[str] = []
    for creator in creators:
        if creator.get("creatorType") not in ("author", None):
            continue
        name = str(creator.get("name") or "").strip()
        if not name:
            first = str(creator.get("firstName") or "").strip()
            last = str(creator.get("lastName") or "").strip()
            name = f"{first} {last}".strip()
        if name:
            result.append(name)
    return tuple(result)


def _snapshot(
    item: dict[str, Any],
    *,
    collection_names: dict[str, str],
    pdf_parent_keys: set[str],
) -> ZoteroItemSnapshot:
    data = dict(item.get("data") or {})
    item_key = str(item.get("key") or "")
    title = str(data.get("title") or "").strip()
    doi = str(data.get("DOI") or "").strip() or None
    url = str(data.get("url") or "").strip()
    tags = tuple(
        name
        for entry in data.get("tags") or []
        if isinstance(entry, dict) and (name := str(entry.get("tag") or "").strip())
    )
    collections = tuple(
        collection_names[key]
        for key in data.get("collections") or []
        if key in collection_names
    )
    venue = (
        data.get("publicationTitle")
        or data.get("proceedingsTitle")
        or data.get("conferenceName")
        or data.get("repository")
    )
    return ZoteroItemSnapshot(
        item_key=item_key,
        title=title,
        authors=_authors(list(data.get("creators") or [])),
        abstract=str(data.get("abstractNote") or "").strip() or None,
        publish_date=_parse_date(
            str(data["date"]) if data.get("date") is not None else None
        ),
        doi=doi,
        tags=tags,
        date_added=str(data.get("dateAdded") or "").strip() or None,
        item_type=str(data.get("itemType") or ""),
        venue=str(venue).strip() or None if venue is not None else None,
        collections=collections,
        has_pdf_attachment=item_key in pdf_parent_keys,
        has_metadata=bool(title or doi or url),
    )


def _annotations_json(annotations: list[dict[str, Any]]) -> str:
    payload = [
        {"key": annotation.get("key"), "data": annotation.get("data") or {}}
        for annotation in annotations
        if annotation.get("key")
    ]
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _page_dimensions(content: bytes) -> PageDimensions:
    dimensions = extract_pdf_page_dimensions(content)
    return tuple(
        (page_index, float(width), float(height))
        for page_index, (width, height) in sorted(dimensions.items())
    )


class DefaultZoteroOperations:
    """Calls remote providers only; it never owns or receives a database Session."""

    def request_token(self) -> ZoteroRequestToken | None:
        result = zotero_auth_client.get_request_token()
        if result is None:
            return None
        return ZoteroRequestToken(
            token=result.oauth_token,
            secret=result.oauth_token_secret,
        )

    def authorize_url(self, *, request_token: ZoteroRequestToken) -> str:
        return zotero_auth_client.get_authorize_url(request_token.token)

    def exchange_access_token(
        self,
        *,
        callback: PreparedZoteroCallback,
        verifier: str,
    ) -> ZoteroAccessToken | None:
        result = zotero_auth_client.get_access_token(
            request_token=callback.request_token.token,
            request_token_secret=callback.request_token.secret,
            verifier=verifier,
        )
        if result is None:
            return None
        return ZoteroAccessToken(
            user_id=result.zotero_user_id,
            api_key=result.api_key,
        )

    def fetch_library(
        self,
        *,
        credentials: ZoteroCredentials,
        limit: int = 100,
    ) -> ZoteroLibrarySnapshot:
        client = self._client(credentials)
        items: list[dict[str, Any]] = []
        start = 0
        page_size = 25
        while len(items) < limit:
            batch = client.get_top_importable_items(limit=page_size, start=start)
            if not batch:
                break
            items.extend(batch[: limit - len(items)])
            if len(batch) < page_size:
                break
            start += page_size
        pdf_parent_keys = client.get_pdf_parent_item_keys()
        collection_names = client.get_collections()
        return ZoteroLibrarySnapshot(
            items=tuple(
                _snapshot(
                    item,
                    collection_names=collection_names,
                    pdf_parent_keys=pdf_parent_keys,
                )
                for item in items
                if item.get("key")
            )
        )

    def fetch_items(
        self,
        *,
        credentials: ZoteroCredentials,
        item_keys: tuple[str, ...],
    ) -> tuple[ZoteroItemSnapshot, ...]:
        client = self._client(credentials)
        items = client.get_items_by_keys(list(item_keys))
        return tuple(
            _snapshot(item, collection_names={}, pdf_parent_keys=set())
            for item in items
            if item.get("key")
        )

    async def fetch_import_content(
        self,
        *,
        credentials: ZoteroCredentials,
        item: ZoteroItemSnapshot,
    ) -> ZoteroImportContent:
        client = self._client(credentials)
        raw_items = await asyncio.to_thread(
            client.get_items_by_keys,
            [item.item_key],
        )
        raw_item = raw_items[0] if raw_items else {"key": item.item_key, "data": {}}
        attachment = await self._fetch_attachment(
            client=client,
            raw_item=raw_item,
            download_pdf=True,
        )
        pdf_content, snapshot, error = attachment
        return ZoteroImportContent(
            item=item,
            attachment=snapshot,
            pdf_content=pdf_content,
            page_dimensions=(
                await asyncio.to_thread(_page_dimensions, pdf_content)
                if pdf_content
                else ()
            ),
            error=error,
        )

    async def fetch_attachment(
        self,
        *,
        credentials: ZoteroCredentials,
        item: ZoteroItemSnapshot,
    ) -> ZoteroAttachmentSnapshot:
        client = self._client(credentials)
        raw_items = await asyncio.to_thread(
            client.get_items_by_keys,
            [item.item_key],
        )
        raw_item = raw_items[0] if raw_items else {"key": item.item_key, "data": {}}
        _content, snapshot, _error = await self._fetch_attachment(
            client=client,
            raw_item=raw_item,
            download_pdf=False,
        )
        return snapshot

    async def fetch_page_dimensions(self, *, source_key: str | None) -> PageDimensions:
        if not source_key:
            return ()
        try:
            content = await asyncio.to_thread(
                s3_service.download_bytes,
                source_key,
            )
            return await asyncio.to_thread(_page_dimensions, content)
        except Exception:
            return ()

    async def fetch_sync_batch(
        self,
        *,
        credentials: ZoteroCredentials,
        targets: tuple[ZoteroSyncTarget, ...],
    ) -> ZoteroSyncBatch:
        client = self._client(credentials)

        async def fetch(target: ZoteroSyncTarget) -> ZoteroSyncUpdate | str:
            try:
                children = await asyncio.to_thread(
                    client.get_children,
                    target.attachment_key,
                )
                annotations = client.get_annotations_for_attachment(children)
                dimensions = await self.fetch_page_dimensions(
                    source_key=target.document_source_key,
                )
                return ZoteroSyncUpdate(
                    target=target,
                    annotations_json=_annotations_json(annotations),
                    page_dimensions=dimensions,
                )
            except Exception:
                return target.item_key

        results = await asyncio.gather(*(fetch(target) for target in targets))
        return ZoteroSyncBatch(
            updates=tuple(
                result for result in results if isinstance(result, ZoteroSyncUpdate)
            ),
            failed_item_keys=tuple(
                result for result in results if isinstance(result, str)
            ),
        )

    async def upload_pdf(self, *, content: bytes) -> None:
        import hashlib

        await asyncio.to_thread(
            s3_service.upload_document_source,
            sha256=hashlib.sha256(content).hexdigest(),
            pdf_bytes=content,
        )

    def record_event(
        self,
        *,
        actor: Actor,
        name: str,
        properties: dict[str, object],
    ) -> None:
        track_event(name, user_id=str(actor.id), properties=properties)

    @staticmethod
    def parse_date_added(value: str | None) -> datetime | None:
        return _parse_added(value)

    @staticmethod
    def _client(credentials: ZoteroCredentials) -> ZoteroApiClient:
        return ZoteroApiClient(
            zotero_user_id=credentials.user_id,
            api_key=credentials.api_key,
        )

    async def _fetch_attachment(
        self,
        *,
        client: ZoteroApiClient,
        raw_item: dict[str, Any],
        download_pdf: bool,
    ) -> tuple[bytes | None, ZoteroAttachmentSnapshot, str | None]:
        item_key = str(raw_item.get("key") or "")
        data = dict(raw_item.get("data") or {})
        children = await asyncio.to_thread(client.get_children, item_key)
        pdf_attachment = client.find_pdf_attachment(children)
        error: str | None = None
        if pdf_attachment is not None:
            attachment_key = str(pdf_attachment.get("key") or "")
            link_mode = str(
                (pdf_attachment.get("data") or {}).get("linkMode") or ""
            ).lower()
            attachment_children = await asyncio.to_thread(
                client.get_children,
                attachment_key,
            )
            annotations = client.get_annotations_for_attachment(attachment_children)
            snapshot = ZoteroAttachmentSnapshot(
                item_key=item_key,
                import_source=ZoteroImportSource.PDF_ATTACHMENT,
                attachment_key=attachment_key or None,
                source_url=None,
                annotations_json=_annotations_json(annotations),
            )
            if not download_pdf:
                return None, snapshot, None
            if link_mode == "linked_file":
                return None, snapshot, "PDF is a linked local file"
            if link_mode == "linked_url":
                return None, snapshot, "PDF is a linked URL"
            try:
                content = await asyncio.to_thread(
                    client.download_attachment_file,
                    attachment_key,
                )
                valid, validation_error = await asyncio.to_thread(
                    validate_pdf_content,
                    content,
                    "zotero",
                )
                if valid:
                    return content, snapshot, None
                error = validation_error or "PDF attachment could not be validated"
            except Exception:
                error = "PDF attachment download failed"
        else:
            error = "No PDF attached to this item in Zotero"

        urls = list(client.resolve_item_urls(data))
        for url in urls:
            valid, content, _validation_error = await asyncio.to_thread(
                validate_url_and_fetch_pdf,
                url,
            )
            if valid and content:
                return (
                    content,
                    ZoteroAttachmentSnapshot(
                        item_key=item_key,
                        import_source=ZoteroImportSource.URL,
                        attachment_key=None,
                        source_url=url,
                        annotations_json="[]",
                    ),
                    None,
                )
        return (
            None,
            ZoteroAttachmentSnapshot(
                item_key=item_key,
                import_source=ZoteroImportSource.URL,
                attachment_key=None,
                source_url=urls[0] if urls else None,
                annotations_json="[]",
            ),
            (
                "Could not download a PDF from the item's URL"
                if urls
                else error or "No PDF available"
            ),
        )


__all__ = ["DefaultZoteroOperations"]
