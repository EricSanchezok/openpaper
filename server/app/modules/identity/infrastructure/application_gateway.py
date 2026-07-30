"""SQLAlchemy adapter for Scholens identity/profile use cases."""

from app.modules.identity.application.identity import IdentityProfile, LocalIdentity
from app.modules.identity.infrastructure.users import user_repository
from sqlalchemy.orm import Session


class SqlAlchemyIdentityGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def ensure_profile(self, *, user_id: int) -> IdentityProfile:
        profile = user_repository.get_or_create_profile(self._db, user_id=user_id)
        return IdentityProfile(
            locale=profile.locale,
            is_admin=profile.is_admin,
            is_blocked=profile.is_blocked,
        )

    def local_identity(self, *, user_id: int) -> LocalIdentity | None:
        user = user_repository.get(self._db, id=user_id)
        if user is None or user.profile is None:
            return None
        return LocalIdentity(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            status=str(user.status),
            email_verified=user.email_verified_at is not None,
            profile=IdentityProfile(
                locale=user.profile.locale,
                is_admin=user.profile.is_admin,
                is_blocked=user.profile.is_blocked,
            ),
        )

    def set_blocked(self, *, user_id: int, blocked: bool) -> str | None:
        user = user_repository.get(self._db, id=user_id)
        if user is None:
            return None
        user_repository.set_blocked(
            self._db,
            user_id=user_id,
            blocked=blocked,
        )
        return user.email
