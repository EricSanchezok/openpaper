"""Secure generation and one-way hashing for Scholens AccessKeys."""

from __future__ import annotations

import hashlib
import re
import secrets

from app.modules.access_keys.application.ports import GeneratedAccessKey

ACCESS_KEY_PREFIX = "sk_scholens_"
ACCESS_KEY_DISPLAY_PREFIX_LENGTH = 20
ACCESS_KEY_PATTERN = re.compile(r"^sk_scholens_[A-Za-z0-9_-]{43}$")


class SecureAccessKeySecrets:
    def generate(self) -> GeneratedAccessKey:
        secret = f"{ACCESS_KEY_PREFIX}{secrets.token_urlsafe(32)}"
        if ACCESS_KEY_PATTERN.fullmatch(secret) is None:
            raise RuntimeError("generated access key has an invalid format")
        return GeneratedAccessKey(
            secret=secret,
            secret_hash=_hash(secret),
            key_prefix=secret[:ACCESS_KEY_DISPLAY_PREFIX_LENGTH],
        )

    def hash_if_valid(self, secret: str) -> str | None:
        if ACCESS_KEY_PATTERN.fullmatch(secret) is None:
            return None
        return _hash(secret)


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()
