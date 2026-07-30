"""HTTP binding for the durable Stripe webhook processor."""

from uuid import uuid4

from app.bootstrap.execution import get_stripe_webhook_processor
from app.modules.billing.application.webhooks import ProcessStripeWebhook
from app.shared.application import RequestReference
from fastapi import APIRouter, Depends, Header, Request

router = APIRouter()


@router.post("/stripe")
async def handle_stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    processor: ProcessStripeWebhook = Depends(get_stripe_webhook_processor),
) -> dict[str, object]:
    payload = await request.body()
    return await processor.process(
        payload=payload,
        signature=stripe_signature,
        request_reference=RequestReference(uuid4()),
    )
