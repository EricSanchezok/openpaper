from __future__ import annotations

import os
from urllib.parse import urlparse

import uvicorn
from dotenv import load_dotenv


LOCAL_DATABASE_URL = (
    "postgresql://scholens_app:replace-with-local-runtime-password@"
    "127.0.0.1:55432/sanchezcloud"
)


def require_local_database_url(database_url: str) -> None:
    """Reject any target outside the registered shared-local PostgreSQL."""
    parsed = urlparse(database_url)
    if (
        parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg2"}
        or parsed.hostname != "127.0.0.1"
        or parsed.port != 55432
        or parsed.path != "/sanchezcloud"
        or parsed.username != "scholens_app"
        or bool(parsed.params or parsed.query or parsed.fragment)
    ):
        raise ValueError(
            "Scholens local startup requires PostgreSQL at 127.0.0.1:55432/sanchezcloud"
        )


def require_local_server_address(host: str, port: int) -> None:
    """Reject stale or externally exposed local-listener settings."""
    if host != "127.0.0.1" or port != 7301:
        raise ValueError("Scholens local API must listen on 127.0.0.1:7301")


def start() -> None:
    """Validate the shared-local target and start the development API."""
    load_dotenv()
    database_url = os.getenv("DATABASE_URL", LOCAL_DATABASE_URL)
    require_local_database_url(database_url)
    require_local_database_url(os.getenv("AUTH_DATABASE_URL", database_url))
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "7301"))
    require_local_server_address(host, port)
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=os.getenv("RELOAD", "false").lower() == "true",
    )
