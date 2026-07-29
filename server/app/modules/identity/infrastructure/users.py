from __future__ import annotations

from app.modules.identity.infrastructure.models import AuthUser, UserProfile
from app.shared.application import Actor
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, joinedload


class UserRepository:
    """Read shared identities and manage Scholens-only profile state."""

    def get(self, db: Session, *, id: int) -> AuthUser | None:
        return db.scalars(
            select(AuthUser)
            .options(joinedload(AuthUser.profile))
            .where(AuthUser.id == id)
        ).first()

    def get_by_email(self, db: Session, *, email: str) -> AuthUser | None:
        return db.scalars(
            select(AuthUser)
            .options(joinedload(AuthUser.profile))
            .where(AuthUser.email == email.lower().strip())
        ).first()

    def get_or_create_profile(self, db: Session, *, user_id: int) -> UserProfile:
        profile = db.scalars(
            select(UserProfile).where(UserProfile.user_id == user_id)
        ).first()
        if profile is not None:
            return profile

        db.execute(
            insert(UserProfile)
            .values(user_id=user_id)
            .on_conflict_do_nothing(index_elements=[UserProfile.user_id])
        )
        db.flush()
        return db.scalars(
            select(UserProfile).where(UserProfile.user_id == user_id)
        ).one()

    def set_blocked(self, db: Session, *, user_id: int, blocked: bool) -> UserProfile:
        profile = self.get_or_create_profile(db, user_id=user_id)
        profile.is_blocked = blocked
        db.flush()
        db.refresh(profile)
        return profile


user_repository = UserRepository()


def actor_from_auth_user(user: AuthUser) -> Actor:
    """Map the shared auth projection into a transport-neutral caller."""
    profile = user.profile
    return Actor.from_identity_projection(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        status=str(user.status),
        email_verified=user.email_verified_at is not None,
        locale=profile.locale if profile else None,
        is_admin=profile.is_admin if profile else False,
        is_blocked=profile.is_blocked if profile else False,
    )
