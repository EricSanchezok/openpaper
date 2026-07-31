"""Existing AI rate and concurrency limits adapted for translation."""

from __future__ import annotations

from uuid import UUID

from app.helpers.ai_limits import (
    AILimitExceeded,
    AIConcurrencyLease,
    acquire_concurrency,
    enforce_rate_limit,
    release_concurrency,
)
from app.modules.translations.application import TranslationCapacityLease
from app.shared.domain import AppError, FailureKind


class RedisTranslationCapacity:
    async def enforce_rate(
        self,
        *,
        user_id: int,
        client_ip: str,
    ) -> None:
        try:
            await enforce_rate_limit(
                user_id=user_id,
                ip_address=client_ip,
                feature="translation",
            )
        except AILimitExceeded as exc:
            raise AppError(
                code=exc.code,
                message="AI request limit exceeded",
                kind=FailureKind.RATE_LIMITED,
            ) from None

    async def acquire(
        self,
        *,
        user_id: int,
        operation_id: UUID,
    ) -> TranslationCapacityLease:
        try:
            lease = await acquire_concurrency(
                user_id=user_id,
                category="interactive",
                operation_id=str(operation_id),
            )
        except AILimitExceeded as exc:
            raise AppError(
                code=exc.code,
                message="AI request limit exceeded",
                kind=FailureKind.RATE_LIMITED,
            ) from None
        return TranslationCapacityLease(key=lease.key, member=lease.member)

    async def release(self, lease: TranslationCapacityLease) -> None:
        await release_concurrency(
            AIConcurrencyLease(key=lease.key, member=lease.member)
        )
