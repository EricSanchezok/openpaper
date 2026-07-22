from __future__ import annotations

import os

import uvicorn

from app.scripts.migrate_all import main as migrate_all


def start() -> None:
    """Migrate the local database and start the development API."""
    migrate_all()
    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("RELOAD", "false").lower() == "true",
    )
