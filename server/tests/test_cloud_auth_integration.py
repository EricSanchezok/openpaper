from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from app.auth import dependencies
from cloud_auth.models.user import UserRecord
from fastapi import HTTPException


def _cloud_user() -> UserRecord:
    return UserRecord(
        id=42,
        email="reader@example.com",
        password_hash="not-used-by-openpaper",
        display_name="Reader",
        status="active",
        email_verified=True,
    )


@pytest.mark.asyncio
async def test_optional_auth_returns_none_without_token() -> None:
    result = await dependencies.get_current_user(None, MagicMock())
    assert result is None


@pytest.mark.asyncio
async def test_cloud_identity_is_enriched_with_openpaper_profile() -> None:
    profile = SimpleNamespace(
        locale="zh-CN",
        is_admin=True,
        is_blocked=False,
    )
    db = MagicMock()
    with patch.object(
        dependencies.user_repository,
        "get_or_create_profile",
        return_value=profile,
    ) as get_profile:
        result = await dependencies.get_current_user(_cloud_user(), db)

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
        dependencies.user_repository,
        "get_or_create_profile",
        return_value=profile,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await dependencies.get_current_user(_cloud_user(), MagicMock())

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "OpenPaper access is suspended"
