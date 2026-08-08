"""Quota and distributed-concurrency adapters for Research generation."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from app.helpers.ai_limits import (
    AILimitExceeded,
    acquire_concurrency,
    ai_limit_app_error,
    enforce_rate_limit,
    release_concurrency_by_id,
)
from app.llm.token_credits import has_token_credits
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind
from sqlalchemy.orm import Session


class SqlGenerationEntitlements:
    def __init__(self, db: Session) -> None:
        self._db = db

    def require_tokens(self, *, actor: Actor) -> None:
        if not has_token_credits(self._db, user=actor):
            raise AppError(
                code="token_quota_exceeded",
                message="Token Credits are exhausted",
                kind=FailureKind.RATE_LIMITED,
            )


class RedisGenerationCapacity:
    async def enforce_rate(
        self,
        *,
        actor: Actor,
        client_ip: str,
        feature: Literal["audio", "data_table"],
    ) -> None:
        try:
            await enforce_rate_limit(
                user_id=actor.id,
                ip_address=client_ip,
                feature=feature,
            )
        except AILimitExceeded as exc:
            raise ai_limit_app_error(
                exc,
                exceeded_message="AI request limit exceeded",
            ) from None

    async def acquire_audio(self, *, actor: Actor, operation_id: UUID) -> None:
        try:
            await acquire_concurrency(
                user_id=actor.id,
                category="background",
                operation_id=str(operation_id),
            )
            try:
                await acquire_concurrency(
                    user_id=actor.id,
                    category="audio",
                    operation_id=str(operation_id),
                )
            except Exception:
                await self.release_background(actor=actor, operation_id=operation_id)
                raise
        except AILimitExceeded as exc:
            raise ai_limit_app_error(
                exc,
                exceeded_message="AI request limit exceeded",
            ) from None

    async def acquire_background(
        self,
        *,
        actor: Actor,
        operation_id: UUID,
    ) -> None:
        try:
            await acquire_concurrency(
                user_id=actor.id,
                category="background",
                operation_id=str(operation_id),
            )
        except AILimitExceeded as exc:
            raise ai_limit_app_error(
                exc,
                exceeded_message="AI request limit exceeded",
            ) from None

    async def release_audio(self, *, actor: Actor, operation_id: UUID) -> None:
        await release_concurrency_by_id(
            user_id=actor.id,
            category="audio",
            operation_id=str(operation_id),
        )
        await self.release_background(actor=actor, operation_id=operation_id)

    async def release_background(
        self,
        *,
        actor: Actor,
        operation_id: UUID,
    ) -> None:
        await release_concurrency_by_id(
            user_id=actor.id,
            category="background",
            operation_id=str(operation_id),
        )
