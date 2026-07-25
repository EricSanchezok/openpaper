from __future__ import annotations

import asyncio

from src.pdf.state import ParserStateStore


class MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.closed = False

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int,
        nx: bool = False,
    ) -> bool:
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def delete(self, key: str) -> int:
        return int(self.values.pop(key, None) is not None)

    async def eval(self, _script: str, _count: int, key: str, token: str) -> int:
        if self.values.get(key) != token:
            return 0
        del self.values[key]
        return 1

    async def aclose(self) -> None:
        self.closed = True


def test_state_checkpoint_and_submit_lock_are_namespaced() -> None:
    async def scenario() -> None:
        redis = MemoryRedis()
        store = ParserStateStore(redis_client=redis)

        await store.save_task_id("job-1", "mineru-task")
        assert await store.get_task_id("job-1") == "mineru-task"

        token = await store.acquire_submit_lock("job-1")
        assert token is not None
        assert await store.acquire_submit_lock("job-1") is None
        await store.release_submit_lock("job-1", token)
        assert await store.acquire_submit_lock("job-1") is not None

        await store.clear("job-1")
        assert await store.get_task_id("job-1") is None
        await store.close()
        assert redis.closed

    asyncio.run(scenario())
