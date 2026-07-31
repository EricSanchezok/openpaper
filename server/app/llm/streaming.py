"""Shared cancellation-aware bridge for blocking provider streams."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import TypeVar, cast

T = TypeVar("T")
_END = object()


def _next_or_end(iterator: Iterator[T]) -> T | object:
    try:
        return next(iterator)
    except StopIteration:
        return _END


async def iterate_in_thread(iterator: Iterator[T]) -> AsyncIterator[T]:
    try:
        while True:
            item = await asyncio.to_thread(_next_or_end, iterator)
            if item is _END:
                break
            yield cast(T, item)
    finally:
        close = getattr(iterator, "close", None)
        if callable(close):
            await asyncio.to_thread(close)


__all__ = ["iterate_in_thread"]
