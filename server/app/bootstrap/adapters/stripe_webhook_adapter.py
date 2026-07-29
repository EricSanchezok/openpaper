"""Infrastructure implementation of the Stripe webhook port."""

from app.bootstrap.adapters.stripe_webhook import (
    process_stripe_webhook,
)
from sqlalchemy.orm import Session


class StripeWebhookAdapter:
    def __init__(self, db: Session) -> None:
        self._db = db

    async def process(
        self,
        *,
        payload: bytes,
        signature: str,
    ) -> dict[str, object]:
        return await process_stripe_webhook(
            payload=payload,
            stripe_signature=signature,
            db=self._db,
        )
