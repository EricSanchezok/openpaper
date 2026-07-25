"""Typed boundary around the untyped PostHog SDK."""

from collections.abc import Mapping
from typing import Protocol

from posthog import Posthog


class PostHogClient(Protocol):
    debug: bool

    def capture(
        self,
        *,
        distinct_id: str,
        event: str,
        properties: Mapping[str, object],
    ) -> object: ...


def create_posthog_client(
    api_key: str,
    *,
    synchronous: bool = False,
) -> PostHogClient:
    return Posthog(
        api_key,
        host="https://us.i.posthog.com",
        sync_mode=synchronous,
        enable_exception_autocapture=True,
    )


def capture_event(
    client: PostHogClient,
    *,
    distinct_id: str,
    event: str,
    properties: Mapping[str, object],
) -> None:
    client.capture(
        distinct_id=distinct_id,
        event=event,
        properties=properties,
    )
