"""Infrastructure implementation of the Stripe webhook port."""

from app.bootstrap.adapters.stripe_webhook import (
    process_stripe_webhook,
)
from sqlalchemy.orm import Session, sessionmaker


class StripeWebhookAdapter:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def process(
        self,
        *,
        payload: bytes,
        signature: str,
    ) -> dict[str, object]:
        with self._session_factory() as session:
            return await process_stripe_webhook(
                payload=payload,
                stripe_signature=signature,
                db=session,
            )
