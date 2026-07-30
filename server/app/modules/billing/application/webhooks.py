"""Transport-neutral contract for verified Stripe webhook processing."""

from __future__ import annotations

from typing import Protocol

from app.shared.application import RequestReference


class ProcessStripeWebhook(Protocol):
    async def process(
        self,
        *,
        payload: bytes,
        signature: str,
        request_reference: RequestReference,
    ) -> dict[str, object]: ...


__all__ = ["ProcessStripeWebhook"]
