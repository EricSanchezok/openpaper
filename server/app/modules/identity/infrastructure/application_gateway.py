"""SQLAlchemy adapter for Scholens identity/profile use cases."""

from app.modules.identity.application.identity import IdentityProfile
from app.modules.identity.infrastructure.users import user_repository
from sqlalchemy.orm import Session


class SqlAlchemyIdentityGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def profile(self, *, user_id: int) -> IdentityProfile:
        profile = user_repository.get_or_create_profile(self._db, user_id=user_id)
        return IdentityProfile(
            locale=profile.locale,
            is_admin=profile.is_admin,
            is_blocked=profile.is_blocked,
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
