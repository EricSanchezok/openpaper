"""Authenticated caller context passed to application use cases."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Actor:
    """The product identity required to authorize a business operation.

    Transport-specific credentials and cloud-auth records are deliberately not
    exposed beyond the identity adapter.
    """

    user_id: int
    email: str
    display_name: str | None
    locale: str | None
    is_admin: bool
    is_blocked: bool

    @property
    def is_active(self) -> bool:
        return not self.is_blocked
