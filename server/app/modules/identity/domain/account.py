"""Pure Scholens product-account authorization rules."""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.domain import AppError, FailureKind


@dataclass(frozen=True, slots=True)
class AccountAccessFacts:
    status: str
    is_blocked: bool
    is_admin: bool

    @property
    def is_active(self) -> bool:
        return self.status == "active" and not self.is_blocked


def require_product_access(facts: AccountAccessFacts) -> None:
    if facts.is_blocked:
        raise AppError(
            code="identity_suspended",
            message="Scholens access is suspended",
            kind=FailureKind.PERMISSION_DENIED,
        )
    if facts.status != "active":
        raise AppError(
            code="identity_inactive",
            message="The Scholens account is not active",
            kind=FailureKind.PERMISSION_DENIED,
        )


def require_administrator(facts: AccountAccessFacts) -> None:
    if not facts.is_admin:
        raise AppError(
            code="admin_required",
            message="Administrator access is required",
            kind=FailureKind.PERMISSION_DENIED,
        )
