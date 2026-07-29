"""Replaceable application boundary for private paper search."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from typing import Protocol

from app.modules.papers.application.contracts.search import (
    PaperSearchQuery,
    PaperSearchRequest,
    PaperSearchResponse,
    PaperSearchStats,
)
from app.shared.application import Actor
from app.shared.domain import AppError

SEARCH_CURSOR_REVISION = 1


class SearchCursorCodec:
    def __init__(self, secret: str) -> None:
        self._secret = secret.encode()

    def encode(self, *, query: str, offset: int) -> str:
        payload = json.dumps(
            {
                "revision": SEARCH_CURSOR_REVISION,
                "query_hash": hashlib.sha256(query.encode()).hexdigest(),
                "offset": offset,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload + signature).decode().rstrip("=")

    def decode(self, *, cursor: str, query: str) -> int:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            decoded = base64.urlsafe_b64decode(padded)
            if len(decoded) <= hashlib.sha256().digest_size:
                raise ValueError("cursor payload is missing")
            payload, signature = decoded[:-32], decoded[-32:]
            expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
            data = json.loads(payload)
            valid = (
                isinstance(data, dict)
                and hmac.compare_digest(signature, expected)
                and data["revision"] == SEARCH_CURSOR_REVISION
                and data["query_hash"] == hashlib.sha256(query.encode()).hexdigest()
                and isinstance(data["offset"], int)
                and not isinstance(data["offset"], bool)
                and data["offset"] >= 0
            )
        except (binascii.Error, KeyError, TypeError, ValueError):
            valid = False
            data = {}
        if not valid:
            raise AppError(
                code="search_cursor_expired",
                message="The search cursor is invalid or expired",
                status_code=409,
            )
        return int(data["offset"])


class PaperSearchPort(Protocol):
    """Algorithm-neutral search capability used by every transport."""

    def search(
        self,
        *,
        actor: Actor,
        request: PaperSearchQuery,
    ) -> PaperSearchResponse: ...

    def stats(self, *, actor: Actor) -> PaperSearchStats: ...


class SearchPapers:
    def __init__(self, search: PaperSearchPort, cursors: SearchCursorCodec) -> None:
        self._search = search
        self._cursors = cursors

    def __call__(
        self,
        *,
        actor: Actor,
        request: PaperSearchRequest,
    ) -> PaperSearchResponse:
        query = request.query.strip()
        offset = (
            self._cursors.decode(cursor=request.cursor, query=query)
            if request.cursor
            else 0
        )
        response = self._search.search(
            actor=actor,
            request=PaperSearchQuery(
                query=query,
                limit=request.limit,
                offset=offset,
            ),
        )
        consumed = offset + len(response.papers)
        next_cursor = (
            self._cursors.encode(query=query, offset=consumed)
            if consumed < response.total_papers
            else None
        )
        return response.model_copy(update={"next_cursor": next_cursor})


class GetPaperSearchStats:
    def __init__(self, search: PaperSearchPort) -> None:
        self._search = search

    def __call__(self, *, actor: Actor) -> PaperSearchStats:
        return self._search.stats(actor=actor)
