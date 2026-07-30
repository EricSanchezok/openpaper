"""Identity onboarding HTTP adapter."""

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import (
    get_application_executor,
    get_onboarding_finisher,
)
from app.modules.identity.application.onboarding import FinishOnboarding
from app.modules.identity.application.onboarding_contracts import (
    CreateOnboardingRequest,
    OnboardingResponse,
)
from app.shared.application import Actor, ApplicationExecutor, OperationContext
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends

onboarding_router = APIRouter()


@onboarding_router.put("", response_model=OnboardingResponse)
async def complete_onboarding(
    request: CreateOnboardingRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    finisher: FinishOnboarding = Depends(get_onboarding_finisher),
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> OnboardingResponse:
    onboarding = executor.command(
        lambda capabilities: capabilities.onboarding.execute(
            actor=actor,
            operation=operation,
            request=request,
        )
    )
    await finisher.execute(
        actor=actor,
        request=request,
        onboarding=onboarding,
    )
    return onboarding
