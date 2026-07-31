"""Authenticated encryption for third-party Connector API keys."""

from __future__ import annotations

import base64
import os

from app.modules.integrations.connectors.domain import ConnectorProvider
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = "v1"


class AesGcmConnectorCredentialCipher:
    def __init__(self, encoded_key: str) -> None:
        try:
            key = base64.urlsafe_b64decode(encoded_key.encode())
        except Exception as exc:
            raise ValueError(
                "CONNECTOR_CREDENTIAL_ENCRYPTION_KEY must be URL-safe base64"
            ) from exc
        if len(key) != 32:
            raise ValueError(
                "CONNECTOR_CREDENTIAL_ENCRYPTION_KEY must decode to 32 bytes"
            )
        self._cipher = AESGCM(key)

    def encrypt(
        self,
        *,
        user_id: int,
        provider: ConnectorProvider,
        plaintext: str,
    ) -> str:
        nonce = os.urandom(12)
        encrypted = self._cipher.encrypt(
            nonce,
            plaintext.encode(),
            _aad(user_id, provider),
        )
        payload = base64.urlsafe_b64encode(nonce + encrypted).decode().rstrip("=")
        return f"{_VERSION}.{payload}"

    def decrypt(
        self,
        *,
        user_id: int,
        provider: ConnectorProvider,
        ciphertext: str,
    ) -> str:
        try:
            version, payload = ciphertext.split(".", 1)
            if version != _VERSION:
                raise ValueError("unsupported credential version")
            padded = payload + "=" * (-len(payload) % 4)
            raw = base64.urlsafe_b64decode(padded)
            return self._cipher.decrypt(
                raw[:12],
                raw[12:],
                _aad(user_id, provider),
            ).decode()
        except Exception as exc:
            raise ValueError("connector credential decryption failed") from exc


def _aad(user_id: int, provider: ConnectorProvider) -> bytes:
    return f"scholens:connector:{_VERSION}:{user_id}:{provider.value}".encode()
