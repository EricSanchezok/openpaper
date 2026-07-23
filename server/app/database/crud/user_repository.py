from __future__ import annotations

from app.database.models import AuthUser, UserProfile
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, joinedload


class UserRepository:
    """Read shared identities and manage OpenPaper-only profile state."""

    def get(self, db: Session, *, id: int) -> AuthUser | None:
        return (
            db.query(AuthUser)
            .options(joinedload(AuthUser.profile))
            .filter(AuthUser.id == id)
            .first()
        )

    def get_by_email(self, db: Session, *, email: str) -> AuthUser | None:
        return (
            db.query(AuthUser)
            .options(joinedload(AuthUser.profile))
            .filter(AuthUser.email == email.lower().strip())
            .first()
        )

    def get_or_create_profile(self, db: Session, *, user_id: int) -> UserProfile:
        profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        if profile is not None:
            return profile

        db.execute(
            insert(UserProfile)
            .values(user_id=user_id)
            .on_conflict_do_nothing(index_elements=[UserProfile.user_id])
        )
        db.commit()
        profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).one()
        return profile

    def set_blocked(self, db: Session, *, user_id: int, blocked: bool) -> UserProfile:
        profile = self.get_or_create_profile(db, user_id=user_id)
        profile.is_blocked = blocked
        db.commit()
        db.refresh(profile)
        return profile


user_repository = UserRepository()
