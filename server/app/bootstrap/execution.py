"""Application executor construction and HTTP dependency."""

from __future__ import annotations

from typing import cast

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.settings import AppSettings
from app.database.database import SessionLocal
from app.shared.application import ApplicationExecutor
from app.shared.infrastructure import SqlAlchemyApplicationExecutor
from fastapi import Request


def create_application_executor(
    settings: AppSettings,
) -> ApplicationExecutor[ApplicationCapabilities]:
    return SqlAlchemyApplicationExecutor(
        SessionLocal,
        lambda session: ApplicationCapabilities(session, settings),
    )


def get_application_executor(
    request: Request,
) -> ApplicationExecutor[ApplicationCapabilities]:
    return cast(
        ApplicationExecutor[ApplicationCapabilities],
        request.app.state.application_executor,
    )
