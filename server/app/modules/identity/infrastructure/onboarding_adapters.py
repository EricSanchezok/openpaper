"""Infrastructure adapters for the onboarding application use case."""

from __future__ import annotations

from app.database.telemetry import track_event
from app.helpers.email import send_profile_email
from app.modules.identity.application.onboarding_contracts import (
    CreateOnboardingRequest,
    OnboardingResponse,
)
from app.modules.identity.infrastructure.cloud_auth import auth_manager
from app.modules.identity.infrastructure.onboarding_repository import (
    OnboardingCreate,
    onboarding_repository,
)
from app.shared.application import Actor
from sqlalchemy.orm import Session


class SqlAlchemyOnboardingWriter:
    def __init__(self, db: Session) -> None:
        self._db = db

    def upsert(
        self,
        *,
        actor: Actor,
        request: CreateOnboardingRequest,
    ) -> OnboardingResponse:
        existing = onboarding_repository.get_by(self._db, user=actor)
        values = request.model_dump(exclude_unset=True, mode="json")
        if existing is None:
            onboarding = onboarding_repository.create(
                self._db,
                obj_in=OnboardingCreate(user_id=actor.id, **values),
            )
        else:
            onboarding = onboarding_repository.update(
                self._db,
                db_obj=existing,
                obj_in=values,
            )
        return OnboardingResponse.model_validate(onboarding)


class CloudAuthDisplayNameWriter:
    async def set_display_name(self, *, user_id: int, display_name: str) -> None:
        await auth_manager.update_profile(user_id, display_name)


class EmailOnboardingNotifier:
    def notify(self, onboarding: OnboardingResponse) -> None:
        send_profile_email(onboarding)


class PostHogOnboardingEventRecorder:
    def __init__(self, db: Session) -> None:
        self._db = db

    def completed(
        self,
        *,
        user_id: int,
        properties: dict[str, object],
    ) -> None:
        track_event(
            "onboarding_completed",
            user_id=str(user_id),
            properties=properties,
            db=self._db,
        )
