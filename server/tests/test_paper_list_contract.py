import asyncio
import json
from unittest.mock import MagicMock

from app.api.paper_api import get_active_paper_ids, get_relevant_papers
from app.database.crud.paper_crud import paper_crud
from app.schemas.user import CurrentUser
from sqlalchemy.orm import Session


def _current_user() -> CurrentUser:
    return CurrentUser(
        id=1,
        email="reader@example.com",
        status="active",
        email_verified=True,
        is_active=True,
    )


def _response_body(response: object) -> dict[str, list[object]]:
    body = getattr(response, "body")
    parsed: dict[str, list[object]] = json.loads(bytes(body))
    return parsed


def test_active_papers_uses_empty_collection_for_new_user(monkeypatch) -> None:
    monkeypatch.setattr(
        paper_crud,
        "get_multi_uploads_completed",
        lambda *_args, **_kwargs: [],
    )

    response = asyncio.run(
        get_active_paper_ids(db=MagicMock(spec=Session), current_user=_current_user())
    )

    assert response.status_code == 200
    assert _response_body(response) == {"papers": []}


def test_relevant_papers_uses_empty_collection_for_new_user(monkeypatch) -> None:
    monkeypatch.setattr(
        paper_crud,
        "get_top_relevant_papers",
        lambda *_args, **_kwargs: [],
    )

    response = asyncio.run(
        get_relevant_papers(db=MagicMock(spec=Session), current_user=_current_user())
    )

    assert response.status_code == 200
    assert _response_body(response) == {"papers": []}
