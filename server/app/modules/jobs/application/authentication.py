"""Replay-protection boundary for signed internal Jobs callbacks."""

from typing import Protocol


class CallbackNonceStore(Protocol):
    def reserve(self, nonce: str) -> bool: ...


class ProtectJobCallback:
    def __init__(self, nonces: CallbackNonceStore) -> None:
        self._nonces = nonces

    def reserve_nonce(self, nonce: str) -> bool:
        return self._nonces.reserve(nonce)
