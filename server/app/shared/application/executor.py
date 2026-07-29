"""Transport-neutral execution boundary for application capabilities."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar

CapabilitiesT = TypeVar("CapabilitiesT", covariant=True)
ResultT = TypeVar("ResultT")


class ApplicationExecutor(Protocol[CapabilitiesT]):
    """Run one complete use case inside one owned transaction boundary."""

    def query(
        self,
        operation: Callable[[CapabilitiesT], ResultT],
    ) -> ResultT: ...

    def command(
        self,
        operation: Callable[[CapabilitiesT], ResultT],
    ) -> ResultT: ...

    async def command_async(
        self,
        operation: Callable[[CapabilitiesT], Awaitable[ResultT]],
    ) -> ResultT: ...
