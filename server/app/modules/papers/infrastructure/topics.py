from app.modules.papers.infrastructure.search_repository import (
    document_search_repository,
)
from sqlalchemy.orm import Session


class SqlAlchemyPaperTopics:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list(self, *, user_id: int) -> list[str]:
        return document_search_repository.list_topics(
            self._db,
            user_id=user_id,
        )
