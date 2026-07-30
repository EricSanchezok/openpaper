"""Verified scalar facts and replay protection for internal Jobs callbacks."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class VerifiedJobCallback:
    request_id: UUID
    delivery_ref: str


class CallbackNonceStore(Protocol):
    def reserve(self, nonce: str) -> bool: ...


class ProtectJobCallback:
    def __init__(self, nonces: CallbackNonceStore) -> None:
        self._nonces = nonces

    def reserve_nonce(self, nonce: str) -> bool:
        return self._nonces.reserve(nonce)


__all__ = ["ProtectJobCallback", "VerifiedJobCallback"]
