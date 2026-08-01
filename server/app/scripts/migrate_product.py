from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)


def main() -> None:
    """Apply only Scholens-owned migrations.

    The independently managed sanchezcloud-identity migration must run first.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    repository_root = Path(__file__).resolve().parents[2]
    alembic_config = Config(str(repository_root / "alembic.ini"))
    alembic_config.set_main_option(
        "script_location", str(repository_root / "migrations")
    )
    command.upgrade(alembic_config, "head")
    logger.info("migration.product.current")


if __name__ == "__main__":
    main()
