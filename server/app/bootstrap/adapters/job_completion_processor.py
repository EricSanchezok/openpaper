"""Owned transaction boundary for asynchronous durable-job completions."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.bootstrap.container import build_job_callbacks


class JobCompletionProcessor:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def complete(
        self,
        *,
        job_id: UUID,
        payload: dict[str, object],
    ) -> object:
        with self._session_factory() as session:
            try:
                result = await build_job_callbacks(db=session).complete(
                    job_id=job_id,
                    payload=payload,
                )
                session.commit()
                return result
            except Exception:
                session.rollback()
                raise
