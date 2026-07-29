from datetime import UTC, datetime
from typing import Callable
from uuid import UUID, uuid4

import pytest
from app.modules.papers.application.contracts.search import (
    PaperSearchQuery,
    PaperSearchRequest,
    PaperSearchResponse,
    PaperSearchResult,
    PaperSearchStats,
)
from app.modules.papers.application.search import SearchCursorCodec, SearchPapers
from app.modules.projects.application.document_visibility import (
    ListAccessibleProjectDocuments,
)
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _paper() -> PaperSearchResult:
    now = datetime.now(UTC)
    return PaperSearchResult(
        document_id=uuid4(),
        title="Search result",
        authors=[],
        abstract=None,
        status="completed",
        publish_date=None,
        created_at=now,
        last_accessed_at=now,
    )


class _SearchBackend:
    def __init__(self) -> None:
        self.requests: list[PaperSearchQuery] = []

    def search(
        self,
        *,
        actor: Actor,
        request: PaperSearchQuery,
    ) -> PaperSearchResponse:
        self.requests.append(request)
        return PaperSearchResponse(
            items=[_paper()],
            total=2,
        )

    def stats(
        self,
        *,
        actor: Actor,
        accessible_project_document_ids: tuple[UUID, ...],
    ) -> PaperSearchStats:
        raise AssertionError("stats is not used by this test")


class _ProjectDocuments:
    def list_accessible_document_ids(
        self,
        *,
        actor: Actor,
        project_id: UUID | None = None,
    ) -> tuple[UUID, ...]:
        return ()


def test_search_cursor_round_trip_uses_backend_neutral_offset() -> None:
    backend = _SearchBackend()
    search = SearchPapers(
        backend,
        SearchCursorCodec("x" * 32),
        ListAccessibleProjectDocuments(_ProjectDocuments()),
    )

    first_page = search(
        actor=_actor(),
        request=PaperSearchRequest(query="  graph retrieval  ", limit=1),
    )
    assert first_page.next_cursor is not None
    assert backend.requests[0].query == "graph retrieval"
    assert backend.requests[0].offset == 0

    second_page = search(
        actor=_actor(),
        request=PaperSearchRequest(
            query="graph retrieval",
            limit=1,
            cursor=first_page.next_cursor,
        ),
    )
    assert backend.requests[1].offset == 1
    assert second_page.next_cursor is None


@pytest.mark.parametrize(
    ("cursor_mutation", "query"),
    [
        (
            lambda cursor: ("A" if cursor[0] != "A" else "B") + cursor[1:],
            "graph retrieval",
        ),
        (lambda cursor: cursor, "different query"),
    ],
)
def test_search_cursor_rejects_tampering_and_query_reuse(
    cursor_mutation: Callable[[str], str],
    query: str,
) -> None:
    codec = SearchCursorCodec("x" * 32)
    cursor = codec.encode(fingerprint="graph retrieval", offset=10)

    with pytest.raises(AppError) as error:
        codec.decode(
            cursor=cursor_mutation(cursor),
            fingerprint=query,
        )

    assert error.value.code == "search_cursor_expired"
    assert error.value.kind is FailureKind.CONFLICT
