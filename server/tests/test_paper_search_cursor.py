from datetime import UTC, datetime
from typing import Callable
from unittest.mock import Mock
from uuid import uuid4

import pytest
from app.bootstrap.adapters.paper_search import (
    PostgresPaperSearch,
    _visibility_condition,
)
from app.modules.papers.application.contracts.search import (
    LibraryPaperCollection,
    PaperCollection,
    PaperSearchFilters,
    PaperSearchQuery,
    PaperSearchRequest,
    PaperSearchResponse,
    PaperSearchResult,
    PaperSearchSort,
    PaperSearchStats,
    SelectedPaperCollection,
)
from app.modules.papers.application.search import SearchCursorCodec, SearchPapers
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.sql import ClauseElement


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
    ) -> PaperSearchStats:
        raise AssertionError("stats is not used by this test")


class _SearchAccess:
    def require_collection_access(
        self,
        *,
        actor: Actor,
        collection: PaperCollection,
    ) -> None:
        pass


def test_search_cursor_round_trip_uses_backend_neutral_offset() -> None:
    backend = _SearchBackend()
    search = SearchPapers(
        backend,
        SearchCursorCodec("x" * 32),
        _SearchAccess(),
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


def test_search_cursor_is_bound_to_the_selected_collection() -> None:
    backend = _SearchBackend()
    search = SearchPapers(
        backend,
        SearchCursorCodec("x" * 32),
        _SearchAccess(),
    )
    first_document = uuid4()
    first_page = search(
        actor=_actor(),
        request=PaperSearchRequest(
            query="graph retrieval",
            limit=1,
            collection=SelectedPaperCollection(document_ids=[first_document]),
        ),
    )

    assert first_page.next_cursor is not None
    with pytest.raises(AppError) as error:
        search(
            actor=_actor(),
            request=PaperSearchRequest(
                query="graph retrieval",
                limit=1,
                cursor=first_page.next_cursor,
                collection=SelectedPaperCollection(document_ids=[uuid4()]),
            ),
        )

    assert error.value.code == "search_cursor_expired"


def test_library_visibility_includes_personal_and_project_access() -> None:
    statement = str(
        _visibility_condition(
            actor=_actor(),
            collection=LibraryPaperCollection(),
        ).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "library_papers" in statement
    assert "project_papers" in statement
    assert "projects" in statement
    assert "project_collaborators" in statement
    assert "owner_id" in statement


def test_library_search_compiles_with_distinct_result_and_visibility_rows() -> None:
    db = Mock(spec=Session)
    compiled_sql: list[str] = []

    def compile_statement(statement: ClauseElement) -> str:
        return " ".join(str(statement.compile(dialect=postgresql.dialect())).split())

    def scalar(statement: ClauseElement) -> int:
        compiled_sql.append(compile_statement(statement))
        return 0

    rows = Mock()
    rows.all.return_value = []

    def execute(statement: ClauseElement) -> Mock:
        compiled_sql.append(compile_statement(statement))
        return rows

    db.scalar.side_effect = scalar
    db.execute.side_effect = execute

    response = PostgresPaperSearch(db).search(
        actor=_actor(),
        request=PaperSearchQuery(
            query="graph retrieval",
            collection=LibraryPaperCollection(),
            filters=PaperSearchFilters(),
            sort=PaperSearchSort.RELEVANCE,
            limit=50,
            offset=0,
        ),
    )

    assert response.items == []
    assert response.total == 0
    assert len(compiled_sql) == 2
    for statement in compiled_sql:
        assert (
            "LEFT OUTER JOIN scholens.library_papers AS actor_library_entry"
            in statement
        )
        assert (
            "EXISTS (SELECT scholens.library_papers.id "
            "FROM scholens.library_papers "
            "WHERE scholens.library_papers.document_id = scholens.documents.id"
            in statement
        )
