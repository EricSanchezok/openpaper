"""Translation adapter over the shared Token Credits policy."""

from __future__ import annotations

from app.llm.token_credits import has_token_credits
from app.shared.application import Actor
from sqlalchemy.orm import Session


class SqlTranslationEntitlements:
    def __init__(self, db: Session) -> None:
        self._db = db

    def has_token_credits(self, *, actor: Actor) -> bool:
        return has_token_credits(self._db, user=actor)
