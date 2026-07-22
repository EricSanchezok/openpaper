from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg
from cloud_auth import (
    AsyncpgUserDatabase,
    AuthConfig,
    RegisterRateLimiter,
    UserManager,
    close_pool,
    create_get_current_user,
    create_get_optional_user,
    create_pool,
    get_auth_router,
    get_user_router,
)
from cloud_auth.email.aliyun import AliyunDirectMailSender
from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)


class AuthRuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUTH_", env_file=".env", extra="ignore", case_sensitive=False
    )

    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/annotated-paper"
    )
    client_id: str = "openpaper"
    jwt_secret: str = "development-only-openpaper-auth-secret"
    jwt_access_token_ttl_minutes: int = 15
    jwt_refresh_token_ttl_days: int = 7
    pg_ssl_root_cert: str = ""
    pg_pool_min_size: int = 2
    pg_pool_max_size: int = 10
    aliyun_dm_access_key_id: str = ""
    aliyun_dm_access_key_secret: str = ""
    aliyun_dm_account_name: str = ""
    aliyun_dm_from_alias: str = "OpenPaper"


settings = AuthRuntimeSettings()
auth_config = AuthConfig(
    client_id=settings.client_id,
    jwt_secret=settings.jwt_secret,
    jwt_access_token_ttl_minutes=settings.jwt_access_token_ttl_minutes,
    jwt_refresh_token_ttl_days=settings.jwt_refresh_token_ttl_days,
)

_auth_pool: asyncpg.Pool | None = None


def get_auth_pool() -> asyncpg.Pool:
    if _auth_pool is None:
        raise RuntimeError("cloud-auth database pool is not initialized")
    return _auth_pool


auth_db = AsyncpgUserDatabase(pool_factory=get_auth_pool)

email_sender = None
if settings.aliyun_dm_account_name:
    email_sender = AliyunDirectMailSender(
        access_key_id=settings.aliyun_dm_access_key_id,
        access_key_secret=settings.aliyun_dm_access_key_secret,
        account_name=settings.aliyun_dm_account_name,
        from_alias=settings.aliyun_dm_from_alias,
    )

auth_manager = UserManager(db=auth_db, email_sender=email_sender, config=auth_config)
get_cloud_user = create_get_current_user(db=auth_db, config=auth_config)
get_optional_cloud_user = create_get_optional_user(db=auth_db, config=auth_config)

cloud_auth_router = get_auth_router(
    user_manager=auth_manager,
    get_current_user=get_cloud_user,
    register_rate_limiter=RegisterRateLimiter(max_success=3, window_seconds=3600),
)
cloud_user_router = get_user_router(
    user_manager=auth_manager,
    get_current_user=get_cloud_user,
)


@asynccontextmanager
async def auth_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _auth_pool

    database_url = make_url(settings.database_url)
    _auth_pool = await create_pool(
        host=database_url.host or "localhost",
        port=database_url.port or 5432,
        database=database_url.database or "postgres",
        user=database_url.username or "postgres",
        password=database_url.password or "",
        ssl_root_cert=settings.pg_ssl_root_cert,
        min_size=settings.pg_pool_min_size,
        max_size=settings.pg_pool_max_size,
    )
    try:
        yield
    finally:
        await close_pool(_auth_pool)
        _auth_pool = None
