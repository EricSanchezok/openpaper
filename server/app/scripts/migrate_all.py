from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from cloud_auth import close_pool, create_pool, run_migrations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)


async def migrate_cloud_auth(database_url: str) -> None:
    parsed_url = make_url(database_url)
    pool = await create_pool(
        host=parsed_url.host or "localhost",
        port=parsed_url.port or 5432,
        database=parsed_url.database or "postgres",
        user=parsed_url.username or "postgres",
        password=parsed_url.password or "",
        ssl_root_cert=os.getenv("AUTH_PG_SSL_ROOT_CERT", ""),
        min_size=1,
        max_size=1,
    )
    try:
        await run_migrations(pool)
    finally:
        await close_pool(pool)


def validate_openpaper_schema(database_url: str) -> None:
    expected_schema = os.getenv("OPENPAPER_DB_SCHEMA", "public")
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            current_schema = connection.execute(text("SELECT current_schema()"))
            if current_schema.scalar_one() != expected_schema:
                raise RuntimeError(
                    "DATABASE_URL must select the OpenPaper schema; "
                    f"expected {expected_schema!r} as current_schema()"
                )
            auth_users = connection.execute(
                text("SELECT to_regclass('auth.users')")
            ).scalar_one()
            if auth_users is None:
                raise RuntimeError("cloud-auth migrations did not create auth.users")
    finally:
        engine.dispose()


def migrate_openpaper() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    alembic_config = Config(str(repository_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(repository_root / "migrations"))
    command.upgrade(alembic_config, "head")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    database_url = os.environ["DATABASE_URL"]
    asyncio.run(migrate_cloud_auth(database_url))
    validate_openpaper_schema(database_url)
    migrate_openpaper()
    logger.info("cloud-auth and OpenPaper migrations are current")


if __name__ == "__main__":
    main()
