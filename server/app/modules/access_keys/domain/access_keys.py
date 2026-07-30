"""Pure AccessKey lifecycle decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AccessKeyStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class AccessKeyFacts:
    expires_at: datetime | None
    revoked_at: datetime | None


def access_key_status(
    facts: AccessKeyFacts,
    *,
    now: datetime,
) -> AccessKeyStatus:
    if facts.revoked_at is not None:
        return AccessKeyStatus.REVOKED
    if facts.expires_at is not None and facts.expires_at <= now:
        return AccessKeyStatus.EXPIRED
    return AccessKeyStatus.ACTIVE
