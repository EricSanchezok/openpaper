from __future__ import annotations

from logging.config import fileConfig
from typing import Any

from alembic import context
from app.database.config import Settings
from app.database.models import Base
from cloud_auth import AUTH_SCHEMA_VERSION
from sqlalchemy import Connection, engine_from_config, pool, text

SCHOLENS_SCHEMA = "scholens"
MIGRATION_TABLE = "schema_migrations"
MIGRATION_LOCK = "scholens-migrations"

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = Settings()
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))
target_metadata = Base.metadata


def _object_schema(obj: Any) -> str | None:
    schema = getattr(obj, "schema", None)
    if isinstance(schema, str):
        return schema
    table = getattr(obj, "table", None)
    table_schema = getattr(table, "schema", None)
    return table_schema if isinstance(table_schema, str) else None


def include_object(
    obj: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Keep auth and Alembic's own ledger outside product autogeneration."""
    del reflected, compare_to
    schema = _object_schema(obj)
    if schema == "auth":
        return False
    return not (
        type_ == "table" and name == MIGRATION_TABLE and schema == SCHOLENS_SCHEMA
    )


def _configure(**kwargs: Any) -> None:
    context.configure(
        target_metadata=target_metadata,
        include_schemas=True,
        include_object=include_object,
        version_table=MIGRATION_TABLE,
        version_table_schema=SCHOLENS_SCHEMA,
        compare_type=True,
        **kwargs,
    )


def _validate_migration_boundary(connection: Connection) -> None:
    owns_schema = connection.execute(
        text(
            "SELECT pg_get_userbyid(nspowner) = current_user "
            "FROM pg_namespace WHERE nspname = :schema"
        ),
        {"schema": SCHOLENS_SCHEMA},
    ).scalar_one_or_none()
    if owns_schema is not True:
        raise RuntimeError(
            "Scholens schema is missing or not owned by the product migration role"
        )

    auth_ledger = connection.execute(
        text("SELECT to_regclass('auth.schema_migrations')")
    ).scalar_one()
    if auth_ledger is None:
        raise RuntimeError(
            "cloud-auth schema must be migrated independently before Scholens"
        )

    auth_version = connection.execute(
        text("SELECT COALESCE(max(version), 0) FROM auth.schema_migrations")
    ).scalar_one()
    if int(auth_version) < AUTH_SCHEMA_VERSION:
        raise RuntimeError(
            f"auth schema version {auth_version} is incompatible; "
            f"version {AUTH_SCHEMA_VERSION} or newer is required"
        )


def run_migrations_offline() -> None:
    _configure(
        url=config.get_main_option("sqlalchemy.url"),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _validate_migration_boundary(connection)
        connection.execute(
            text("SELECT pg_advisory_lock(hashtext(:name))"), {"name": MIGRATION_LOCK}
        )
        connection.commit()
        try:
            _configure(connection=connection)
            with context.begin_transaction():
                context.run_migrations()
        finally:
            if connection.in_transaction():
                connection.rollback()
            connection.execute(
                text("SELECT pg_advisory_unlock(hashtext(:name))"),
                {"name": MIGRATION_LOCK},
            )
            connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
