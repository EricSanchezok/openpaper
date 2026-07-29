"""Signed opaque cursors shared by replaceable paginated capabilities."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json

from app.shared.domain import AppError, FailureKind


class SignedCursorCodec:
    def __init__(
        self,
        secret: str,
        *,
        revision: str,
        error_code: str,
    ) -> None:
        self._secret = secret.encode()
        self._revision = revision
        self._error_code = error_code

    def encode(self, *, fingerprint: str, offset: int) -> str:
        payload = json.dumps(
            {
                "revision": self._revision,
                "request_hash": hashlib.sha256(fingerprint.encode()).hexdigest(),
                "offset": offset,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload + signature).decode().rstrip("=")

    def decode(self, *, cursor: str, fingerprint: str) -> int:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            decoded = base64.urlsafe_b64decode(padded)
            if len(decoded) <= hashlib.sha256().digest_size:
                raise ValueError("cursor payload is missing")
            payload, signature = decoded[:-32], decoded[-32:]
            expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
            data = json.loads(payload)
            valid = (
                isinstance(data, dict)
                and hmac.compare_digest(signature, expected)
                and data["revision"] == self._revision
                and data["request_hash"]
                == hashlib.sha256(fingerprint.encode()).hexdigest()
                and isinstance(data["offset"], int)
                and not isinstance(data["offset"], bool)
                and data["offset"] >= 0
            )
        except (binascii.Error, KeyError, TypeError, ValueError):
            valid = False
            data = {}
        if not valid:
            raise AppError(
                code=self._error_code,
                message="The cursor is invalid or expired",
                kind=FailureKind.CONFLICT,
            )
        return int(data["offset"])
