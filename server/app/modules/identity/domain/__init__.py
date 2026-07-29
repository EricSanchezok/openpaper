"""Identity domain rules."""

from .account import (
    AccountAccessFacts,
    require_administrator,
    require_product_access,
)

__all__ = [
    "AccountAccessFacts",
    "require_administrator",
    "require_product_access",
]
