"""HTTP binding for the durable Stripe webhook processor."""

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.shared.application import ApplicationExecutor
from fastapi import APIRouter, Depends, Header, Request

router = APIRouter()


@router.post("/stripe")
async def handle_stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> dict[str, object]:
    payload = await request.body()
    return await executor.command_async(
        lambda capabilities: capabilities.stripe_webhooks(
            payload=payload,
            signature=stripe_signature,
        )
    )
