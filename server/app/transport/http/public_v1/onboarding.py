"""Identity onboarding HTTP adapter."""

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.identity.application.onboarding_contracts import (
    CreateOnboardingRequest,
    OnboardingResponse,
)
from app.shared.application import Actor, ApplicationExecutor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends

onboarding_router = APIRouter()


@onboarding_router.put("", response_model=OnboardingResponse)
async def complete_onboarding(
    request: CreateOnboardingRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    actor: Actor = Depends(get_required_user),
) -> OnboardingResponse:
    return await executor.command_async(
        lambda capabilities: capabilities.onboarding.execute(
            actor=actor,
            request=request,
        )
    )
