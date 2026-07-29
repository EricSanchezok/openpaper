"""HTTP adapters for the Zotero integration."""

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.bootstrap.settings import AppSettings
from app.modules.integrations.zotero.application.contracts import (
    ZoteroConnectResponse,
    ZoteroImportRequest,
    ZoteroImportResponse,
    ZoteroImportStatusListResponse,
    ZoteroLibraryResponse,
    ZoteroStatusResponse,
    ZoteroSyncResponse,
)
from app.shared.application import Actor, ApplicationExecutor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import RedirectResponse

zotero_router = APIRouter()
zotero_oauth_router = APIRouter()


@zotero_oauth_router.get("/connect", response_model=ZoteroConnectResponse)
def zotero_connect(
    current_user: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ZoteroConnectResponse:
    return executor.command(
        lambda capabilities: capabilities.zotero.connect(actor=current_user)
    )


@zotero_oauth_router.get("/callback", response_class=RedirectResponse)
def zotero_callback(
    request: Request,
    oauth_token: str = Query(...),
    oauth_verifier: str = Query(...),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> RedirectResponse:
    settings: AppSettings = request.app.state.settings
    success = executor.command(
        lambda capabilities: capabilities.zotero.callback(
            oauth_token=oauth_token,
            oauth_verifier=oauth_verifier,
        )
    )
    state = "connected" if success else "error"
    return RedirectResponse(
        url=f"{settings.client_domain.rstrip('/')}/settings?zotero={state}",
        status_code=status.HTTP_302_FOUND,
    )


@zotero_router.get("/connection", response_model=ZoteroStatusResponse)
def zotero_status(
    current_user: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ZoteroStatusResponse:
    return executor.query(
        lambda capabilities: capabilities.zotero.status(actor=current_user)
    )


@zotero_router.delete(
    "/connection",
    status_code=status.HTTP_204_NO_CONTENT,
)
def zotero_disconnect(
    current_user: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> Response:
    executor.command(
        lambda capabilities: capabilities.zotero.disconnect(actor=current_user)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@zotero_router.get("/library-items", response_model=ZoteroLibraryResponse)
def zotero_library(
    current_user: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ZoteroLibraryResponse:
    return executor.query(
        lambda capabilities: capabilities.zotero.library(actor=current_user)
    )


@zotero_router.post(
    "/imports",
    response_model=ZoteroImportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def zotero_import(
    request: ZoteroImportRequest,
    idempotency_key: str | None = Header(default=None, max_length=128),
    current_user: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ZoteroImportResponse:
    return await executor.command_async(
        lambda capabilities: capabilities.zotero.import_items(
            actor=current_user,
            request=request,
            idempotency_key=idempotency_key,
        )
    )


@zotero_router.post(
    "/sync-runs",
    response_model=ZoteroSyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def zotero_sync(
    current_user: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ZoteroSyncResponse:
    return await executor.command_async(
        lambda capabilities: capabilities.zotero.sync(actor=current_user)
    )


@zotero_router.get("/imports", response_model=ZoteroImportStatusListResponse)
def zotero_import_status_list(
    item_keys: list[str] | None = Query(None),
    current_user: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ZoteroImportStatusListResponse:
    return executor.query(
        lambda capabilities: capabilities.zotero.imports(
            actor=current_user,
            item_keys=item_keys,
        )
    )
