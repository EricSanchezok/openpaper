"""API routes for the Discover feature."""

from app.api.types import ApiData as ApiResponse

import json
import logging
from collections.abc import AsyncGenerator

from app.auth.dependencies import get_required_user
from app.database.crud.discover_crud import discover_search_crud
from app.database.database import get_db
from app.database.telemetry import track_event
from app.helpers.ai_limits import (
    AILimitExceeded,
    acquire_concurrency,
    enforce_rate_limit,
    release_concurrency,
)
from app.helpers.discover import run_discover_pipeline
from app.llm.token_credits import has_token_credits, llm_usage_context
from app.schemas.discover import DISCOVER_SOURCES, DiscoverSearchRequest
from app.database.models import JsonValue
from app.schemas.user import CurrentUser
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import TypeAdapter
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

discover_router = APIRouter()

_DISCOVER_RESULTS_ADAPTER = TypeAdapter(dict[str, list[dict[str, JsonValue]]])

END_DELIMITER = "END_OF_STREAM"


@discover_router.post("/search")
async def discover_search(
    request: DiscoverSearchRequest,
    http_request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> StreamingResponse:
    """Search for research papers by decomposing a question into subqueries."""

    if not has_token_credits(db, user=current_user):
        raise HTTPException(
            status_code=429,
            detail={
                "code": "token_quota_exceeded",
                "message": "Your weekly Token Credits are exhausted.",
                "retryable": False,
            },
        )
    try:
        await enforce_rate_limit(
            user_id=int(current_user.id),
            ip_address=http_request.client.host if http_request.client else "unknown",
            feature="discover",
        )
        concurrency_lease = await acquire_concurrency(
            user_id=int(current_user.id),
            category="interactive",
        )
    except AILimitExceeded as exc:
        raise HTTPException(status_code=429, detail={"code": exc.code}) from None

    async def run_response_generator() -> AsyncGenerator[str, None]:
        collected_subqueries: list[str] = []
        collected_results: dict[str, list[dict[str, object]]] = {}

        try:
            async for chunk in run_discover_pipeline(
                request.question,
                request.sources,
                request.sort,
                request.only_open_access,
                request.year_filter,
            ):
                chunk_type = chunk.get("type")

                if chunk_type == "subqueries":
                    collected_subqueries = chunk["content"]
                elif chunk_type == "results":
                    subquery = chunk.get("subquery", "")
                    collected_results[subquery] = chunk.get("content", [])
                elif chunk_type == "done":
                    # Persist the search
                    saved = discover_search_crud.create(
                        db,
                        question=request.question,
                        subqueries=collected_subqueries,
                        results=_DISCOVER_RESULTS_ADAPTER.validate_python(
                            collected_results
                        ),
                        user=current_user,
                    )

                    # Determine search mode based on sources
                    use_openalex = request.sources and "openalex" in request.sources
                    search_mode = "scholarly" if use_openalex else "explore"

                    track_event(
                        "did_discover_search",
                        properties={
                            "question": request.question,
                            "num_subqueries": len(collected_subqueries),
                            "num_results": sum(
                                len(v) for v in collected_results.values()
                            ),
                            "mode": search_mode,
                            "sources": request.sources,
                            "sort": request.sort,
                            "only_open_access": request.only_open_access,
                            "year_filter": request.year_filter,
                        },
                        user_id=str(current_user.id),
                        db=db,
                    )

                    # Include the search ID in the done chunk
                    chunk["search_id"] = str(saved.id) if saved else None

                yield f"{json.dumps(chunk)}{END_DELIMITER}"

        except Exception as e:
            logger.exception("Error in discover pipeline")
            track_event(
                "discover_search_error",
                properties={
                    "question": request.question,
                    "error_type": type(e).__name__,
                },
                user_id=str(current_user.id),
                db=db,
            )
            yield f"{json.dumps({'type': 'error', 'content': 'discover_failed'})}{END_DELIMITER}"

    async def response_generator() -> AsyncGenerator[str, None]:
        try:
            with llm_usage_context(
                user_id=int(current_user.id),
                feature="discover",
            ):
                async for event in run_response_generator():
                    yield event
        finally:
            await release_concurrency(concurrency_lease)

    return StreamingResponse(response_generator(), media_type="text/event-stream")


@discover_router.get("/history")
async def discover_history(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ApiResponse:
    """Get the user's past discover searches."""
    searches = discover_search_crud.get_history(db, user=current_user, limit=20)
    return [
        {
            "id": str(s.id),
            "question": s.question,
            "subqueries": s.subqueries,
            "results": s.results,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in searches
    ]


@discover_router.get("/sources")
async def discover_sources() -> ApiResponse:
    """Get the list of available source filters for discover search."""
    return [
        {"key": key, "label": info["label"], "description": info["description"]}
        for key, info in DISCOVER_SOURCES.items()
    ]


@discover_router.get("/{search_id}")
async def discover_get(
    search_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ApiResponse:
    """Get a single discover search by ID."""
    search = discover_search_crud.get_by_id(db, search_id=search_id, user=current_user)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")

    track_event(
        "did_view_discover_search",
        properties={"search_id": search_id},
        user_id=str(current_user.id),
        db=db,
    )

    return {
        "id": str(search.id),
        "question": search.question,
        "subqueries": search.subqueries,
        "results": search.results,
        "created_at": search.created_at.isoformat() if search.created_at else None,
    }
