"""Authentication and replay protection for Jobs -> Server requests."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from datetime import UTC, datetime, timedelta

from app.database.database import get_db
from app.database.models import JobsWebhookNonce
from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


async def verify_jobs_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> None:
    secret = os.getenv("JOBS_WEBHOOK_SIGNING_SECRET")
    if not secret or len(secret.encode()) < 32:
        raise HTTPException(status_code=503, detail="jobs_webhook_not_configured")

    timestamp = request.headers.get("X-Jobs-Timestamp", "")
    nonce = request.headers.get("X-Jobs-Nonce", "")
    signature = request.headers.get("X-Jobs-Signature", "")
    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid_jobs_signature") from exc

    if abs(int(time.time()) - timestamp_value) > 300 or not nonce or len(nonce) > 64:
        raise HTTPException(status_code=401, detail="expired_jobs_signature")

    body = await request.body()
    query = request.url.query
    target = request.url.path + (f"?{query}" if query else "")
    canonical = "\n".join(
        (
            timestamp,
            nonce,
            request.method.upper(),
            target,
            hashlib.sha256(body).hexdigest(),
        )
    ).encode()
    expected = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="invalid_jobs_signature")

    try:
        db.execute(
            delete(JobsWebhookNonce).where(
                JobsWebhookNonce.created_at < datetime.now(UTC) - timedelta(minutes=10)
            )
        )
        db.add(JobsWebhookNonce(nonce=nonce))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="jobs_webhook_replayed") from exc
