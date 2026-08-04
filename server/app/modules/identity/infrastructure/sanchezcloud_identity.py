from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from collections.abc import Awaitable, Callable
from typing import AsyncIterator, cast

import asyncpg
from sanchezcloud_identity import (
    AsyncpgUserDatabase,
    AuthConfig,
    RegisterRateLimiter,
    UserManager,
    close_pool,
    create_pool,
)
from sanchezcloud_identity.dependencies import (
    create_get_current_user,
    create_get_optional_user,
)
from sanchezcloud_identity.email.aliyun import AliyunDirectMailSender
from sanchezcloud_identity.exceptions import AuthError, DBError
from sanchezcloud_identity.models.user import UserRecord
from sanchezcloud_identity.routers import (
    RefreshCookieConfig,
    get_auth_router,
    get_user_router,
)
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)
SCHOLENS_AUTH_CLIENT_ID = "scholens"
_DEVELOPMENT_JWT_SECRET = "development-only-scholens-auth-secret"


class AuthRuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUTH_", env_file=".env", extra="ignore", case_sensitive=False
    )

    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://scholens_app:replace-with-local-runtime-password@"
        "127.0.0.1:55432/sanchezcloud",
    )
    jwt_secret: str = _DEVELOPMENT_JWT_SECRET
    jwt_access_token_ttl_minutes: int = 15
    jwt_refresh_token_ttl_days: int = 7
    account_lockout_threshold: int = 5
    account_lockout_duration_minutes: int = 15
    pg_ssl_root_cert: str = ""
    pg_pool_min_size: int = 2
    pg_pool_max_size: int = 10
    aliyun_dm_access_key_id: str = ""
    aliyun_dm_access_key_secret: str = ""
    aliyun_dm_account_name: str = ""
    aliyun_dm_from_alias: str = "Scholens"
    aliyun_dm_reply_to_address: bool = True
    public_web_url: str = "http://127.0.0.1:7300"


settings = AuthRuntimeSettings()


def build_auth_config(runtime_settings: AuthRuntimeSettings) -> AuthConfig:
    return AuthConfig(
        client_id=SCHOLENS_AUTH_CLIENT_ID,
        jwt_secret=runtime_settings.jwt_secret,
        jwt_access_token_ttl_minutes=runtime_settings.jwt_access_token_ttl_minutes,
        jwt_refresh_token_ttl_days=runtime_settings.jwt_refresh_token_ttl_days,
        account_lockout_threshold=runtime_settings.account_lockout_threshold,
        account_lockout_duration_minutes=(
            runtime_settings.account_lockout_duration_minutes
        ),
    )


auth_config = build_auth_config(settings)


def build_refresh_cookie_config(*, environment: str) -> RefreshCookieConfig:
    return RefreshCookieConfig(
        name="scholens_refresh",
        max_age_seconds=settings.jwt_refresh_token_ttl_days * 24 * 60 * 60,
        secure=environment.lower() == "production",
        samesite="strict",
        path="/api/v1/auth",
    )


refresh_cookie_config = build_refresh_cookie_config(
    environment=os.getenv("ENVIRONMENT", "development")
)

_auth_pool: asyncpg.Pool | None = None


def get_auth_pool() -> asyncpg.Pool:
    if _auth_pool is None:
        raise RuntimeError("sanchezcloud-identity database pool is not initialized")
    return _auth_pool


auth_db = AsyncpgUserDatabase(pool_factory=get_auth_pool)


def build_auth_email_sender(
    runtime_settings: AuthRuntimeSettings,
) -> AliyunDirectMailSender | None:
    if not runtime_settings.aliyun_dm_account_name:
        return None
    public_web_url = runtime_settings.public_web_url.rstrip("/")
    return AliyunDirectMailSender(
        access_key_id=runtime_settings.aliyun_dm_access_key_id,
        access_key_secret=runtime_settings.aliyun_dm_access_key_secret,
        account_name=runtime_settings.aliyun_dm_account_name,
        verification_url=f"{public_web_url}/login?mode=verify",
        password_reset_url=f"{public_web_url}/login?mode=reset",
        from_alias=runtime_settings.aliyun_dm_from_alias,
        brand="Scholens",
        reply_to_address=runtime_settings.aliyun_dm_reply_to_address,
    )


email_sender = build_auth_email_sender(settings)

auth_manager = UserManager(db=auth_db, email_sender=email_sender, config=auth_config)
_unchecked_identity_user = cast(
    "Callable[..., Awaitable[UserRecord]]",
    create_get_current_user(db=auth_db, config=auth_config),
)
_unchecked_optional_identity_user = cast(
    "Callable[..., Awaitable[UserRecord | None]]",
    create_get_optional_user(db=auth_db, config=auth_config),
)
_required_bearer = HTTPBearer(scheme_name="BearerAuth")
_optional_bearer = HTTPBearer(auto_error=False, scheme_name="BearerAuth")


async def _require_active_session(
    user: UserRecord,
    credentials: HTTPAuthorizationCredentials,
) -> UserRecord:
    try:
        session_id = auth_manager.session_id_from_access_token(credentials.credentials)
        if not await auth_manager.touch_session(user.id, session_id):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session revoked or expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except DBError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
            headers={"Retry-After": "5"},
        ) from exc
    return user


async def get_identity_user(
    credentials: HTTPAuthorizationCredentials = Depends(_required_bearer),
) -> UserRecord:
    return await authenticate_identity_access_token(credentials.credentials)


async def authenticate_identity_access_token(access_token: str) -> UserRecord:
    """Validate one Bearer access token without depending on an HTTP request."""
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=access_token,
    )
    user = await _unchecked_identity_user(credentials=credentials)
    return await _require_active_session(user, credentials)


async def get_optional_identity_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
) -> UserRecord | None:
    if "authorization" not in request.headers:
        return None
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await _unchecked_optional_identity_user(credentials=credentials)
    if user is None:
        return None
    return await _require_active_session(user, credentials)


sanchezcloud_identity_router = get_auth_router(
    user_manager=auth_manager,
    get_current_user=get_identity_user,
    register_rate_limiter=RegisterRateLimiter(max_attempts=3, window_seconds=3600),
    refresh_cookie=refresh_cookie_config,
    uniform_login_errors=True,
)
identity_user_router = get_user_router(
    user_manager=auth_manager,
    get_current_user=get_identity_user,
)


@asynccontextmanager
async def auth_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _auth_pool

    if os.getenv("ENVIRONMENT", "development").lower() == "production":
        if settings.jwt_secret == _DEVELOPMENT_JWT_SECRET:
            raise RuntimeError("AUTH_JWT_SECRET must be set in production")
        if len(settings.jwt_secret.encode("utf-8")) < 32:
            raise RuntimeError("AUTH_JWT_SECRET must contain at least 32 UTF-8 bytes")
        email_values = (
            settings.aliyun_dm_access_key_id,
            settings.aliyun_dm_access_key_secret,
            settings.aliyun_dm_account_name,
        )
        if not all(email_values):
            raise RuntimeError(
                "Aliyun DirectMail credentials are required for production registration"
            )

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
