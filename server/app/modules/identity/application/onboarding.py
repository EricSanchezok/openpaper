"""Complete the product onboarding use case."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.shared.application import Actor, OperationContext

from .onboarding_contracts import CreateOnboardingRequest, OnboardingResponse

IDENTITY_ONBOARDING_SAVED = OperationAction("identity.onboarding_saved")


@dataclass(frozen=True, slots=True)
class OnboardingSaveResult:
    response: OnboardingResponse
    changed: bool


class OnboardingWriter(Protocol):
    def upsert(
        self,
        *,
        actor: Actor,
        request: CreateOnboardingRequest,
    ) -> OnboardingSaveResult: ...


class DisplayNameWriter(Protocol):
    async def set_display_name(self, *, user_id: int, display_name: str) -> None: ...


class OnboardingNotifier(Protocol):
    def notify(self, onboarding: OnboardingResponse) -> None: ...


class OnboardingEventRecorder(Protocol):
    def completed(
        self,
        *,
        user_id: int,
        properties: dict[str, object],
    ) -> None: ...


class SaveOnboarding:
    def __init__(
        self,
        *,
        writer: OnboardingWriter,
        journal: OperationJournal,
    ) -> None:
        self._writer = writer
        self._journal = journal

    def execute(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request: CreateOnboardingRequest,
    ) -> OnboardingResponse:
        result = self._writer.upsert(actor=actor, request=request)
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=IDENTITY_ONBOARDING_SAVED,
                resources=(
                    ResourceRef("user", str(actor.id)),
                    ResourceRef("onboarding", str(result.response.id)),
                ),
            )
        return result.response


class FinishOnboarding:
    def __init__(
        self,
        *,
        display_names: DisplayNameWriter,
        notifier: OnboardingNotifier,
        events: OnboardingEventRecorder,
    ) -> None:
        self._display_names = display_names
        self._notifier = notifier
        self._events = events

    async def execute(
        self,
        *,
        actor: Actor,
        request: CreateOnboardingRequest,
        onboarding: OnboardingResponse,
    ) -> None:
        if not actor.display_name:
            await self._display_names.set_display_name(
                user_id=actor.id,
                display_name=request.name,
            )
        self._notifier.notify(onboarding)
        self._events.completed(
            user_id=actor.id,
            properties={
                "name": request.name,
                "email": str(request.email),
                "company": request.company,
                "job_titles_other": request.job_titles_other,
                "research_fields_other": request.research_fields_other,
                "reading_frequency": request.reading_frequency,
                "job_titles": _split_values(request.job_titles),
                "research_fields": _split_values(request.research_fields),
            },
        )


def _split_values(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").lower().split(",") if item.strip()]
