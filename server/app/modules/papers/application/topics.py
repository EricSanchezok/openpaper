"""Paper-topic suggestions derived from the user's accessible corpus."""

import random
from typing import Protocol

from app.shared.application import Actor
from pydantic import BaseModel


class TopicListResponse(BaseModel):
    items: list[str]
    next_cursor: str | None = None


class PaperTopicPort(Protocol):
    def list(self, *, user_id: int) -> list[str]: ...


class PaperTopics:
    def __init__(self, topics: PaperTopicPort) -> None:
        self._topics = topics

    def __call__(self, *, actor: Actor) -> TopicListResponse:
        topics = self._topics.list(user_id=actor.id)
        random.shuffle(topics)
        return TopicListResponse(items=topics)
