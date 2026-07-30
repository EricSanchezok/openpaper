"""Type-preserving canonical digests for non-secret transport references."""

from __future__ import annotations

import hashlib
import struct
from uuid import UUID

type CanonicalDigestValue = str | int | UUID | None


def _encode_value(value: CanonicalDigestValue) -> bytes:
    if isinstance(value, bool):
        raise TypeError("boolean values are not canonical digest scalars")
    if isinstance(value, UUID):
        tag = b"u"
        payload = value.bytes
    elif isinstance(value, int):
        tag = b"i"
        payload = str(value).encode("ascii")
    elif isinstance(value, str):
        tag = b"s"
        payload = value.encode("utf-8")
    elif value is None:
        tag = b"n"
        payload = b""
    else:
        raise TypeError(f"unsupported canonical digest value: {type(value).__name__}")
    return tag + struct.pack(">I", len(payload)) + payload


def canonical_sha256(
    domain: str,
    *values: CanonicalDigestValue,
) -> str:
    """Hash typed, length-prefixed scalars under a versioned domain."""

    if not domain:
        raise ValueError("canonical digest domain must not be empty")
    encoded = bytearray(_encode_value(domain))
    encoded.extend(struct.pack(">I", len(values)))
    for value in values:
        encoded.extend(_encode_value(value))
    return hashlib.sha256(encoded).hexdigest()
