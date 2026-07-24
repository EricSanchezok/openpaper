import asyncio
import difflib
import functools
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, Tuple, TypeVar, cast

import openai

logger = logging.getLogger(__name__)
P = ParamSpec("P")
R = TypeVar("R")


class LLMBlockedError(Exception):
    """The model declined to produce output for a reason that retrying won't fix
    (safety filter, recitation, prompt-level block, malformed function call)."""


# Exceptions that should trigger a retry with backoff. LLMBlockedError is
# deliberately excluded — retrying a safety block just burns time and tokens.
RETRYABLE_EXCEPTIONS = (
    ValueError,
    json.JSONDecodeError,
    openai.InternalServerError,  # 500, 503
    openai.RateLimitError,  # 429
    openai.APIConnectionError,  # Network issues
    openai.APITimeoutError,  # Timeouts
)


def retry_llm_operation(
    max_retries: int = 3, delay: float = 1.0
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Decorator to retry LLM operations that may fail due to API errors or validation issues.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        delay: Base delay between retries in seconds (default: 1.0)
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            last_exception: BaseException | None = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except RETRYABLE_EXCEPTIONS as e:
                    last_exception = e
                    if attempt < max_retries:
                        # Calculate exponential backoff with jitter
                        backoff_time = (
                            delay * (2**attempt) * (0.5 + 0.5 * random.random())
                        )
                        logger.warning(
                            f"Retry {attempt+1}/{max_retries} for {func.__name__}: {type(e).__name__}: {str(e)[:100]}. Retrying in {backoff_time:.2f}s"
                        )
                        time.sleep(backoff_time)
                    else:
                        logger.warning(
                            f"All {max_retries} retries failed for {func.__name__}"
                        )

            # If we reach here, all retries failed
            if last_exception is not None:
                logger.error(
                    f"Final failure after {max_retries} retries for {func.__name__}: {str(last_exception)}"
                )
                raise last_exception
            raise RuntimeError("Retry loop ended without a result")

        # Create async version for async functions
        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            last_exception: BaseException | None = None

            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    return await cast(Awaitable[Any], result)
                except RETRYABLE_EXCEPTIONS as e:
                    last_exception = e
                    if attempt < max_retries:
                        # Calculate exponential backoff with jitter
                        backoff_time = (
                            delay * (2**attempt) * (0.5 + 0.5 * random.random())
                        )
                        logger.warning(
                            f"Retry {attempt+1}/{max_retries} for {func.__name__}: {type(e).__name__}: {str(e)[:100]}. Retrying in {backoff_time:.2f}s"
                        )
                        await asyncio.sleep(backoff_time)
                    else:
                        logger.warning(
                            f"All {max_retries} retries failed for {func.__name__}"
                        )

            # If we reach here, all retries failed
            if last_exception is not None:
                logger.error(
                    f"Final failure after {max_retries} retries for {func.__name__}: {str(last_exception)}"
                )
                raise last_exception
            raise RuntimeError("Retry loop ended without a result")

        # Return appropriate wrapper based on if the function is async or not
        if asyncio.iscoroutinefunction(func):
            return cast(Callable[P, R], async_wrapper)
        return wrapper

    return decorator


def find_offsets(target: str, full_text: str) -> Tuple[int, int]:
    """
    Find the start and end offsets of a target string within a full text.
    Returns a tuple of (start_offset, end_offset).
    """
    start_offset = full_text.find(target)
    if start_offset == -1:
        # Run a fuzzy search if exact match not found
        matcher = difflib.SequenceMatcher(None, full_text, target)
        match = matcher.find_longest_match(0, len(full_text), 0, len(target))
        if match.size == 0:
            return -1, -1  # No match found

        start_offset = match.a  # Start index of the match in full_text
        end_offset = start_offset + match.size

    if start_offset == -1:
        return -1, -1

    end_offset = start_offset + len(target)
    return start_offset, end_offset
