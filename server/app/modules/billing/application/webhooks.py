"""Stripe webhook application boundary."""

from __future__ import annotations

from typing import Protocol


class StripeWebhookPort(Protocol):
    async def process(
        self,
        *,
        payload: bytes,
        signature: str,
    ) -> dict[str, object]: ...


class ProcessStripeWebhook:
    def __init__(self, processor: StripeWebhookPort) -> None:
        self._processor = processor

    async def __call__(
        self,
        *,
        payload: bytes,
        signature: str,
    ) -> dict[str, object]:
        return await self._processor.process(
            payload=payload,
            signature=signature,
        )
