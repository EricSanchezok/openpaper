"""Process lifecycle for authentication and durable-job dispatch."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.modules.identity.infrastructure.cloud_auth import auth_lifespan
from app.modules.jobs.infrastructure.dispatcher import run_job_dispatcher
from fastapi import FastAPI


@asynccontextmanager
async def app_lifespan(application: FastAPI) -> AsyncIterator[None]:
    stop_dispatcher = asyncio.Event()
    async with auth_lifespan(application):
        dispatcher = asyncio.create_task(
            run_job_dispatcher(stop_dispatcher),
            name="jobs-outbox-dispatcher",
        )
        try:
            yield
        finally:
            stop_dispatcher.set()
            await dispatcher
