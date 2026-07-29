"""Identity onboarding HTTP adapter."""

from app.database.database import get_db
from app.bootstrap.providers import build_complete_onboarding
from app.modules.identity.application.onboarding_contracts import (
    CreateOnboardingRequest,
    OnboardingResponse,
)
from app.shared.application import Actor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

onboarding_router = APIRouter()


@onboarding_router.put("", response_model=OnboardingResponse)
async def complete_onboarding(
    request: CreateOnboardingRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_required_user),
) -> OnboardingResponse:
    handler = build_complete_onboarding(db=db)
    return await handler.execute(actor=actor, request=request)
