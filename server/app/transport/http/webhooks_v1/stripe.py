"""HTTP binding for the durable Stripe webhook processor."""

from app.database.database import get_db
from app.bootstrap.container import build_stripe_webhook_processor
from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

router = APIRouter()


@router.post("/stripe")
async def handle_stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return await build_stripe_webhook_processor(db=db)(
        payload=await request.body(),
        signature=stripe_signature,
    )
