"""Signed opaque cursors shared by replaceable paginated capabilities."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from typing import NoReturn, cast

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
        return self._encode(
            fingerprint=fingerprint,
            position={"offset": offset},
        )

    def encode_keyset(
        self,
        *,
        fingerprint: str,
        values: tuple[str, ...],
    ) -> str:
        """Sign a transport-opaque keyset position."""

        return self._encode(
            fingerprint=fingerprint,
            position={"keyset": list(values)},
        )

    def _encode(
        self,
        *,
        fingerprint: str,
        position: dict[str, object],
    ) -> str:
        payload = json.dumps(
            {
                "revision": self._revision,
                "request_hash": hashlib.sha256(fingerprint.encode()).hexdigest(),
                **position,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload + signature).decode().rstrip("=")

    def decode(self, *, cursor: str, fingerprint: str) -> int:
        data = self._decode(cursor=cursor, fingerprint=fingerprint)
        offset = data.get("offset")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            self._raise_invalid()
        return offset

    def decode_keyset(
        self,
        *,
        cursor: str,
        fingerprint: str,
        arity: int,
    ) -> tuple[str, ...]:
        """Verify and return a keyset position with a fixed shape."""

        data = self._decode(cursor=cursor, fingerprint=fingerprint)
        values = data.get("keyset")
        if (
            not isinstance(values, list)
            or len(values) != arity
            or any(not isinstance(value, str) for value in values)
        ):
            self._raise_invalid()
        return tuple(cast(list[str], values))

    def _decode(self, *, cursor: str, fingerprint: str) -> dict[str, object]:
        data: dict[str, object] = {}
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            decoded = base64.urlsafe_b64decode(padded)
            if len(decoded) <= hashlib.sha256().digest_size:
                raise ValueError("cursor payload is missing")
            payload, signature = decoded[:-32], decoded[-32:]
            expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
            decoded_data: object = json.loads(payload)
            if not isinstance(decoded_data, dict):
                raise ValueError("cursor payload must be an object")
            data = cast(dict[str, object], decoded_data)
            valid = (
                hmac.compare_digest(signature, expected)
                and data["revision"] == self._revision
                and data["request_hash"]
                == hashlib.sha256(fingerprint.encode()).hexdigest()
            )
        except (binascii.Error, KeyError, TypeError, ValueError):
            valid = False
            data = {}
        if not valid:
            self._raise_invalid()
        return data

    def _raise_invalid(self) -> NoReturn:
        raise AppError(
            code=self._error_code,
            message="The cursor is invalid or expired",
            kind=FailureKind.CONFLICT,
        )
