from __future__ import annotations

import logging
import os
import random
from datetime import UTC, datetime

from app.auth.dependencies import get_admin_user, get_required_user
from app.auth.zotero import zotero_auth_client
from app.database.crud.paper_crud import paper_crud
from app.database.crud.user_repository import user_repository
from app.database.crud.zotero_crud import zotero_crud
from app.database.crud.zotero_import_crud import zotero_import_crud
from app.database.database import get_db
from app.database.telemetry import track_event
from app.schemas.user import CurrentUser
from app.schemas.zotero import (
    ZoteroConnectResponse,
    ZoteroDisconnectResponse,
    ZoteroStatusResponse,
)
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
auth_router = APIRouter()
client_domain = os.getenv("CLIENT_DOMAIN", "http://localhost:3000")


class BlockUserRequest(BaseModel):
    user_id: int
    blocked: bool


@auth_router.get("/topics")
async def get_topics(
    current_user: CurrentUser = Depends(get_required_user),
    db: Session = Depends(get_db),
) -> list[str]:
    topics = paper_crud.get_topics(db, user=current_user)
    random.shuffle(topics)
    return topics


@auth_router.post("/admin/block")
async def block_user(
    request: BlockUserRequest,
    admin_user: CurrentUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    target_user = user_repository.get(db, id=request.user_id)
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    user_repository.set_blocked(db, user_id=request.user_id, blocked=request.blocked)
    action = "blocked" if request.blocked else "unblocked"
    logger.info(
        "OpenPaper user %s %s by %s", target_user.email, action, admin_user.email
    )
    return {"success": True, "message": f"User {action} successfully"}


@auth_router.get("/zotero/connect", response_model=ZoteroConnectResponse)
async def zotero_connect(
    current_user: CurrentUser = Depends(get_required_user),
    db: Session = Depends(get_db),
) -> ZoteroConnectResponse:
    request_token = zotero_auth_client.get_request_token()
    if request_token is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to get request token",
        )

    zotero_crud.delete_pending_for_user(db=db, user_id=current_user.id)
    zotero_crud.create_pending(
        db=db,
        user_id=current_user.id,
        oauth_token=request_token.oauth_token,
        oauth_token_secret=request_token.oauth_token_secret,
    )
    return ZoteroConnectResponse(
        auth_url=zotero_auth_client.get_authorize_url(request_token.oauth_token)
    )


@auth_router.get("/zotero/callback", response_class=RedirectResponse)
async def zotero_callback(
    oauth_token: str = Query(...),
    oauth_verifier: str = Query(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    error_redirect = f"{client_domain}/settings?zotero=error"
    pending = zotero_crud.get_pending_by_token(db=db, oauth_token=oauth_token)
    if pending is None or pending.user_id is None:
        return RedirectResponse(url=error_redirect, status_code=status.HTTP_302_FOUND)

    expires_at = pending.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        zotero_crud.delete_pending(db=db, pending=pending)
        return RedirectResponse(url=error_redirect, status_code=status.HTTP_302_FOUND)

    access_token = zotero_auth_client.get_access_token(
        request_token=oauth_token,
        request_token_secret=pending.oauth_token_secret,
        verifier=oauth_verifier,
    )
    if access_token is None:
        return RedirectResponse(url=error_redirect, status_code=status.HTTP_302_FOUND)

    zotero_crud.upsert_connection(
        db=db,
        user_id=pending.user_id,
        zotero_user_id=access_token.zotero_user_id,
        api_key=access_token.api_key,
    )
    zotero_crud.delete_pending(db=db, pending=pending)
    track_event("zotero_connected", user_id=str(pending.user_id), db=db)
    return RedirectResponse(
        url=f"{client_domain}/settings?zotero=connected",
        status_code=status.HTTP_302_FOUND,
    )


@auth_router.get("/zotero/status", response_model=ZoteroStatusResponse)
async def zotero_status(
    current_user: CurrentUser = Depends(get_required_user),
    db: Session = Depends(get_db),
) -> ZoteroStatusResponse:
    connection = zotero_crud.get_by_user_id(db=db, user_id=current_user.id)
    if connection is None:
        return ZoteroStatusResponse(connected=False)

    return ZoteroStatusResponse(
        connected=True,
        connected_at=connection.created_at,
        last_synced_at=zotero_import_crud.get_max_last_synced_at(
            db, user_id=current_user.id
        ),
    )


@auth_router.delete("/zotero/disconnect", response_model=ZoteroDisconnectResponse)
async def zotero_disconnect(
    current_user: CurrentUser = Depends(get_required_user),
    db: Session = Depends(get_db),
) -> ZoteroDisconnectResponse:
    deleted = zotero_crud.delete_by_user_id(db=db, user_id=current_user.id)
    if not deleted:
        return ZoteroDisconnectResponse(
            success=False, message="No Zotero account connected"
        )
    return ZoteroDisconnectResponse(success=True, message="Zotero account disconnected")
