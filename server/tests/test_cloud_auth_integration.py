from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.settings import AppSettings
from app.database import admin_auth
from app.database.models import AuthUser, Base
from app.modules.identity.infrastructure import cloud_auth as runtime
from app.modules.identity.infrastructure import application_gateway
from app.transport.http.public_v1 import auth_dependencies as dependencies
from app.shared.domain import AppError, FailureKind
from app.shared.infrastructure import SqlAlchemyApplicationExecutor
from cloud_auth.models.user import UserRecord
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import configure_mappers


def _cloud_user() -> UserRecord:
    return UserRecord(
        id=42,
        email="reader@example.com",
        password_hash="not-used-by-scholens",
        display_name="Reader",
        status="active",
        email_verified=True,
    )


def _executor(db: MagicMock) -> SqlAlchemyApplicationExecutor[ApplicationCapabilities]:
    return SqlAlchemyApplicationExecutor(
        MagicMock(return_value=db),
        lambda session: ApplicationCapabilities(session, AppSettings()),
    )


def test_every_orm_table_has_an_explicit_owner_schema() -> None:
    assert Base.metadata.schema == "scholens"
    assert not hasattr(Base, "to_dict")
    assert AuthUser.__table__.schema == "auth"
    assert "deleted_at" not in AuthUser.__table__.columns
    assert {
        table.schema
        for table in Base.metadata.tables.values()
        if table is not AuthUser.__table__
    } == {"scholens"}


def test_all_orm_mappers_and_relationships_configure() -> None:
    configure_mappers()

    assert len(Base.registry.mappers) > 0
    assert all(
        mapper.persist_selectable is not None for mapper in Base.registry.mappers
    )


@pytest.mark.asyncio
async def test_optional_auth_returns_none_without_token() -> None:
    result = await dependencies.get_current_user(None, _executor(MagicMock()))
    assert result is None


@pytest.mark.asyncio
async def test_cloud_identity_is_enriched_with_scholens_profile() -> None:
    profile = SimpleNamespace(
        locale="zh-CN",
        is_admin=True,
        is_blocked=False,
    )
    db = MagicMock()
    with patch.object(
        application_gateway.user_repository,
        "get_or_create_profile",
        return_value=profile,
    ) as get_profile:
        result = await dependencies.get_current_user(_cloud_user(), _executor(db))

    assert result is not None
    assert result.id == 42
    assert result.email == "reader@example.com"
    assert result.display_name == "Reader"
    assert result.locale == "zh-CN"
    assert result.is_admin is True
    assert result.is_active is True
    get_profile.assert_called_once_with(db, user_id=42)


@pytest.mark.asyncio
async def test_product_block_does_not_modify_shared_account() -> None:
    profile = SimpleNamespace(locale=None, is_admin=False, is_blocked=True)
    with patch.object(
        application_gateway.user_repository,
        "get_or_create_profile",
        return_value=profile,
    ):
        with pytest.raises(AppError) as exc_info:
            await dependencies.get_current_user(
                _cloud_user(),
                _executor(MagicMock()),
            )

    assert exc_info.value.kind is FailureKind.PERMISSION_DENIED
    assert exc_info.value.message == "Scholens access is suspended"


def test_refresh_cookie_is_scoped_to_scholens_auth_routes() -> None:
    config = runtime.build_refresh_cookie_config(environment="development")

    assert config.name == "scholens_refresh"
    assert config.path == "/api/v1/auth"
    assert config.max_age_seconds == 7 * 24 * 60 * 60
    assert config.secure is False
    assert config.samesite == "strict"


def test_refresh_cookie_is_secure_in_production() -> None:
    config = runtime.build_refresh_cookie_config(environment="production")

    assert config.secure is True


def test_auth_config_uses_scholens_lockout_settings() -> None:
    runtime_settings = runtime.AuthRuntimeSettings(
        _env_file=None,
        jwt_secret="x" * 32,
        account_lockout_threshold=7,
        account_lockout_duration_minutes=45,
    )

    config = runtime.build_auth_config(runtime_settings)

    assert config.client_id == "scholens"
    assert config.account_lockout_threshold == 7
    assert config.account_lockout_duration_minutes == 45


def test_auth_email_sender_uses_scholens_action_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_settings = runtime.AuthRuntimeSettings(
        _env_file=None,
        aliyun_dm_access_key_id="key-id",
        aliyun_dm_access_key_secret="key-secret",
        aliyun_dm_account_name="sender@example.com",
        public_web_url="https://scholens.example/",
    )
    factory = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(runtime, "AliyunDirectMailSender", factory)

    runtime.build_auth_email_sender(runtime_settings)

    assert factory.call_args.kwargs["verification_url"] == (
        "https://scholens.example/login?mode=verify"
    )
    assert factory.call_args.kwargs["password_reset_url"] == (
        "https://scholens.example/login?mode=reset"
    )
    assert factory.call_args.kwargs["brand"] == "Scholens"
    assert factory.call_args.kwargs["reply_to_address"] is True


@pytest.mark.asyncio
async def test_access_token_requires_active_scholens_session() -> None:
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="access")
    with (
        patch.object(
            runtime.auth_manager, "session_id_from_access_token", return_value=17
        ),
        patch.object(
            runtime.auth_manager,
            "touch_session",
            new=AsyncMock(return_value=False),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await runtime._require_active_session(_cloud_user(), credentials)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Session revoked or expired"


@pytest.mark.asyncio
async def test_admin_login_uses_cloud_auth_and_product_role() -> None:
    request = SimpleNamespace(
        form=AsyncMock(
            return_value={"username": "reader@example.com", "password": "secret"}
        ),
        headers={"user-agent": "pytest"},
        session={},
    )
    backend = admin_auth.AdminAuthenticationBackend(secret_key="x" * 32)

    with (
        patch.object(
            admin_auth.auth_manager,
            "login",
            new=AsyncMock(return_value=("access", "discarded-refresh")),
        ) as login,
        patch.object(
            admin_auth.auth_db,
            "get_user_by_email",
            new=AsyncMock(return_value=_cloud_user()),
        ),
        patch.object(
            admin_auth.auth_manager,
            "session_id_from_access_token",
            return_value=23,
        ),
        patch.object(admin_auth.asyncio, "to_thread", new=AsyncMock(return_value=True)),
    ):
        result = await backend.login(request)

    assert result is True
    assert request.session == {
        "scholens_admin_user_id": 42,
        "scholens_admin_session_id": 23,
    }
    login.assert_awaited_once_with(
        "reader@example.com",
        "secret",
        user_agent="pytest",
    )


@pytest.mark.asyncio
async def test_non_admin_login_revokes_new_cloud_session() -> None:
    request = SimpleNamespace(
        form=AsyncMock(
            return_value={"username": "reader@example.com", "password": "secret"}
        ),
        headers={},
        session={},
    )
    backend = admin_auth.AdminAuthenticationBackend(secret_key="x" * 32)

    with (
        patch.object(
            admin_auth.auth_manager,
            "login",
            new=AsyncMock(return_value=("access", "discarded-refresh")),
        ),
        patch.object(
            admin_auth.auth_db,
            "get_user_by_email",
            new=AsyncMock(return_value=_cloud_user()),
        ),
        patch.object(
            admin_auth.auth_manager,
            "session_id_from_access_token",
            return_value=23,
        ),
        patch.object(
            admin_auth.auth_manager,
            "logout",
            new=AsyncMock(),
        ) as logout,
        patch.object(
            admin_auth.asyncio, "to_thread", new=AsyncMock(return_value=False)
        ),
    ):
        result = await backend.login(request)

    assert result is False
    logout.assert_awaited_once_with(42, 23)


def test_admin_session_secret_fails_closed_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "short")

    with pytest.raises(RuntimeError, match="at least 32"):
        admin_auth.admin_session_secret()
