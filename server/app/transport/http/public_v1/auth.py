"""HTTP adapters for product-specific identity capabilities."""

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.identity.application.contracts import (
    SetUserBlockedRequest,
    SetUserBlockedResponse,
)
from app.modules.papers.application.topics import TopicListResponse
from app.shared.application import Actor, ApplicationExecutor, OperationContext
from app.transport.http.public_v1.auth_dependencies import (
    get_admin_user,
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends

topics_router = APIRouter()
admin_router = APIRouter()


@topics_router.get("/topics", response_model=TopicListResponse)
def get_topics(
    current_user: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> TopicListResponse:
    return executor.query(
        lambda capabilities: capabilities.paper_topics(actor=current_user)
    )


@admin_router.put(
    "/users/{user_id}/block",
    response_model=SetUserBlockedResponse,
)
def block_user(
    user_id: int,
    request: SetUserBlockedRequest,
    admin_user: Actor = Depends(get_admin_user),
    operation: OperationContext = Depends(get_required_operation),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> SetUserBlockedResponse:
    return executor.command(
        lambda capabilities: capabilities.identity.set_blocked(
            actor=admin_user,
            operation=operation,
            user_id=user_id,
            request=request,
        )
    )
