"""HTTP binding for the durable Stripe webhook processor."""

from app.database.database import get_db
from app.services.stripe_webhook import process_stripe_webhook
from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

router = APIRouter()


@router.post("/stripe")
async def handle_stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return await process_stripe_webhook(
        request=request,
        stripe_signature=stripe_signature,
        db=db,
    )
