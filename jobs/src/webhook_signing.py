"""HMAC signing for Jobs -> Server requests."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

import requests


def _secret() -> bytes:
    value = os.getenv("JOBS_WEBHOOK_SIGNING_SECRET")
    if not value or len(value.encode()) < 32:
        raise RuntimeError("JOBS_WEBHOOK_SIGNING_SECRET is required")
    return value.encode()


def post_signed_json(
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float,
) -> requests.Response:
    body = (
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        if payload is not None
        else b""
    )
    timestamp = str(int(time.time()))
    nonce = str(uuid.uuid4())
    parsed = urlsplit(url)
    target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join((timestamp, nonce, "POST", target, body_hash)).encode()
    signature = hmac.new(_secret(), canonical, hashlib.sha256).hexdigest()
    return requests.post(
        url,
        data=body,
        timeout=timeout,
        headers={
            "Content-Type": "application/json",
            "X-Jobs-Timestamp": timestamp,
            "X-Jobs-Nonce": nonce,
            "X-Jobs-Signature": signature,
        },
    )
