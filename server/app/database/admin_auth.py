from __future__ import annotations

import asyncio
import os

from app.modules.identity.infrastructure.sanchezcloud_identity import (
    auth_db,
    auth_manager,
)
from app.modules.identity.infrastructure.users import user_repository
from app.database.database import SessionLocal
from sanchezcloud_identity.exceptions import AuthError
from fastapi import Request
from sqladmin.authentication import AuthenticationBackend

_DEVELOPMENT_SESSION_SECRET = "development-only-scholens-admin-session-secret"


def admin_session_secret() -> str:
    secret = os.getenv("ADMIN_SESSION_SECRET", _DEVELOPMENT_SESSION_SECRET)
    if os.getenv("ENVIRONMENT", "development").lower() == "production":
        if len(secret.encode("utf-8")) < 32:
            raise RuntimeError(
                "ADMIN_SESSION_SECRET must contain at least 32 UTF-8 bytes in production"
            )
    return secret


class AdminAuthenticationBackend(AuthenticationBackend):
    """Authenticate SQLAdmin with shared identity and Scholens product role."""

    @staticmethod
    def _is_scholens_admin(user_id: int) -> bool:
        with SessionLocal() as db:
            user = user_repository.get(db, id=user_id)
            return bool(
                user is not None
                and user.status == "active"
                and user.profile is not None
                and user.profile.is_admin
                and not user.profile.is_blocked
            )

    async def login(self, request: Request) -> bool:
        form = await request.form()
        username, password = form.get("username"), form.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            return False

        try:
            user = await auth_db.get_user_by_email(username)
            if user is None:
                return False
            access_token, _ = await auth_manager.login(
                username,
                password,
                user_agent=request.headers.get("user-agent"),
            )
            session_id = auth_manager.session_id_from_access_token(access_token)
        except AuthError:
            return False

        try:
            is_admin = await asyncio.to_thread(self._is_scholens_admin, user.id)
        except Exception:
            await auth_manager.logout(user.id, session_id)
            raise
        if not is_admin:
            await auth_manager.logout(user.id, session_id)
            return False

        request.session["scholens_admin_user_id"] = user.id
        request.session["scholens_admin_session_id"] = session_id
        return True

    async def logout(self, request: Request) -> bool:
        user_id = request.session.get("scholens_admin_user_id")
        session_id = request.session.get("scholens_admin_session_id")
        if isinstance(user_id, int) and isinstance(session_id, int):
            await auth_manager.logout(user_id, session_id)
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        user_id = request.session.get("scholens_admin_user_id")
        session_id = request.session.get("scholens_admin_session_id")
        if not isinstance(user_id, int) or not isinstance(session_id, int):
            return False
        if not await auth_manager.touch_session(user_id, session_id):
            request.session.clear()
            return False
        is_admin = await asyncio.to_thread(self._is_scholens_admin, user_id)
        if not is_admin:
            await auth_manager.logout(user_id, session_id)
            request.session.clear()
        return is_admin


def build_admin_authentication_backend() -> AdminAuthenticationBackend:
    is_production = os.getenv("ENVIRONMENT", "development").lower() == "production"
    return AdminAuthenticationBackend(
        secret_key=admin_session_secret(),
        same_site="strict",
        https_only=is_production,
        max_age=7 * 24 * 60 * 60,
    )
