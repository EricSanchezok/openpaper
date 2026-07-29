"""HTTP adapters for the Zotero integration."""

from app.bootstrap.container import build_zotero
from app.bootstrap.settings import AppSettings
from app.database.database import get_db
from app.modules.integrations.zotero.application.contracts import (
    ZoteroConnectResponse,
    ZoteroImportRequest,
    ZoteroImportResponse,
    ZoteroImportStatusListResponse,
    ZoteroLibraryResponse,
    ZoteroStatusResponse,
    ZoteroSyncResponse,
)
from app.shared.application import Actor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

zotero_router = APIRouter()
zotero_oauth_router = APIRouter()


@zotero_oauth_router.get("/connect", response_model=ZoteroConnectResponse)
def zotero_connect(
    current_user: Actor = Depends(get_required_user),
    db: Session = Depends(get_db),
) -> ZoteroConnectResponse:
    return build_zotero(db=db).connect(actor=current_user)


@zotero_oauth_router.get("/callback", response_class=RedirectResponse)
def zotero_callback(
    request: Request,
    oauth_token: str = Query(...),
    oauth_verifier: str = Query(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    settings: AppSettings = request.app.state.settings
    success = build_zotero(db=db).callback(
        oauth_token=oauth_token,
        oauth_verifier=oauth_verifier,
    )
    state = "connected" if success else "error"
    return RedirectResponse(
        url=f"{settings.client_domain.rstrip('/')}/settings?zotero={state}",
        status_code=status.HTTP_302_FOUND,
    )


@zotero_router.get("/connection", response_model=ZoteroStatusResponse)
def zotero_status(
    current_user: Actor = Depends(get_required_user),
    db: Session = Depends(get_db),
) -> ZoteroStatusResponse:
    return build_zotero(db=db).status(actor=current_user)


@zotero_router.delete(
    "/connection",
    status_code=status.HTTP_204_NO_CONTENT,
)
def zotero_disconnect(
    current_user: Actor = Depends(get_required_user),
    db: Session = Depends(get_db),
) -> Response:
    build_zotero(db=db).disconnect(actor=current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@zotero_router.get("/library-items", response_model=ZoteroLibraryResponse)
def zotero_library(
    current_user: Actor = Depends(get_required_user),
    db: Session = Depends(get_db),
) -> ZoteroLibraryResponse:
    return build_zotero(db=db).library(actor=current_user)


@zotero_router.post(
    "/imports",
    response_model=ZoteroImportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def zotero_import(
    request: ZoteroImportRequest,
    idempotency_key: str | None = Header(default=None, max_length=128),
    current_user: Actor = Depends(get_required_user),
    db: Session = Depends(get_db),
) -> ZoteroImportResponse:
    return await build_zotero(db=db).import_items(
        actor=current_user,
        request=request,
        idempotency_key=idempotency_key,
    )


@zotero_router.post(
    "/sync-runs",
    response_model=ZoteroSyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def zotero_sync(
    current_user: Actor = Depends(get_required_user),
    db: Session = Depends(get_db),
) -> ZoteroSyncResponse:
    return await build_zotero(db=db).sync(actor=current_user)


@zotero_router.get("/imports", response_model=ZoteroImportStatusListResponse)
def zotero_import_status_list(
    item_keys: list[str] | None = Query(None),
    current_user: Actor = Depends(get_required_user),
    db: Session = Depends(get_db),
) -> ZoteroImportStatusListResponse:
    return build_zotero(db=db).imports(
        actor=current_user,
        item_keys=item_keys,
    )
