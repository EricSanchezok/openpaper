"""Shared cancellation-aware bridge for blocking provider streams."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

T = TypeVar("T")
_END = object()
_BUFFERED_ITEMS = 16
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Value(Generic[T]):
    value: T


@dataclass(frozen=True, slots=True)
class _Failure:
    error: BaseException


def _queue_safely(
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue[_Value[T] | _Failure | object],
    item: _Value[T] | _Failure | object,
    *,
    stopped: threading.Event,
    slots: threading.Semaphore | None,
) -> bool:
    if slots is not None:
        while not stopped.is_set():
            if slots.acquire(timeout=0.1):
                break
        else:
            return False
    try:
        loop.call_soon_threadsafe(queue.put_nowait, item)
    except RuntimeError:
        # The event loop can finish before a cancelled blocking read unwinds.
        if slots is not None:
            slots.release()
        return False
    return True


def _read_iterator(
    *,
    iterator: Iterator[T],
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue[_Value[T] | _Failure | object],
    stopped: threading.Event,
    slots: threading.Semaphore,
) -> None:
    try:
        while not stopped.is_set():
            try:
                item = next(iterator)
            except StopIteration:
                break
            if stopped.is_set():
                break
            if not _queue_safely(
                loop,
                queue,
                _Value(item),
                stopped=stopped,
                slots=slots,
            ):
                break
    except BaseException as exc:
        if not stopped.is_set():
            _queue_safely(
                loop,
                queue,
                _Failure(exc),
                stopped=stopped,
                slots=slots,
            )
    finally:
        close = getattr(iterator, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                logger.exception("Blocking LLM iterator close failed")
        _queue_safely(
            loop,
            queue,
            _END,
            stopped=stopped,
            slots=None,
        )


def _consume_background_failure(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    try:
        error = task.exception()
    except Exception as exc:
        error = exc
    if error is not None:
        logger.error(
            "Blocking LLM background operation failed",
            exc_info=(type(error), error, error.__traceback__),
        )


async def iterate_in_thread(iterator: Iterator[T]) -> AsyncIterator[T]:
    """Read one blocking iterator on one worker and cancel it without closing
    the Python generator from a competing thread.

    Iterators backed by an external stream may expose a thread-safe ``cancel``
    method. It is invoked promptly when the async consumer disconnects; the
    worker remains the sole owner of ``next`` and ``close``.
    """

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[_Value[T] | _Failure | object] = asyncio.Queue()
    stopped = threading.Event()
    slots = threading.Semaphore(_BUFFERED_ITEMS)
    worker = asyncio.create_task(
        asyncio.to_thread(
            _read_iterator,
            iterator=iterator,
            loop=loop,
            queue=queue,
            stopped=stopped,
            slots=slots,
        )
    )
    completed = False
    try:
        while True:
            item = await queue.get()
            if item is _END:
                completed = True
                await worker
                break
            slots.release()
            if isinstance(item, _Failure):
                completed = True
                await worker
                raise item.error
            yield cast(_Value[T], item).value
    finally:
        stopped.set()
        if not completed:
            cancel = getattr(iterator, "cancel", None)
            if callable(cancel):
                cancel_task = asyncio.create_task(asyncio.to_thread(cancel))
                cancel_task.add_done_callback(_consume_background_failure)
            worker.add_done_callback(_consume_background_failure)


__all__ = ["iterate_in_thread"]
