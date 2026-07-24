from __future__ import annotations

import os

import uvicorn
from dotenv import load_dotenv

from app.scripts.migrate_product import main as migrate_product


def start() -> None:
    """Migrate the local database and start the development API."""
    load_dotenv()
    migrate_product()
    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("RELOAD", "false").lower() == "true",
    )
