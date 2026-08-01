"""Stable classification of provider failures."""

from __future__ import annotations

import openai

from app.llm.backend import LLMUsageSettlementError
from app.shared.domain import AppError, FailureKind


def classify_llm_error(error: BaseException, *, stage: str) -> AppError:
    if isinstance(error, AppError):
        return error
    if isinstance(error, openai.APITimeoutError):
        return AppError(
            code="llm_stream_timeout",
            message="The model stopped responding before the operation completed.",
            kind=FailureKind.DEPENDENCY_FAILURE,
            details={"stage": stage},
            retryable=True,
        )
    if isinstance(error, openai.RateLimitError):
        return AppError(
            code="llm_provider_rate_limited",
            message="The model provider is temporarily rate limited.",
            kind=FailureKind.RATE_LIMITED,
            details={"stage": stage},
            retryable=True,
        )
    if isinstance(error, openai.AuthenticationError):
        return AppError(
            code="llm_provider_authentication_failed",
            message="The model provider is not configured correctly.",
            kind=FailureKind.DEPENDENCY_FAILURE,
            details={"stage": stage},
            retryable=False,
        )
    if isinstance(error, openai.APIConnectionError):
        return AppError(
            code="llm_provider_unavailable",
            message="The model provider is temporarily unavailable.",
            kind=FailureKind.DEPENDENCY_FAILURE,
            details={"stage": stage},
            retryable=True,
        )
    if isinstance(error, openai.BadRequestError):
        return AppError(
            code="llm_provider_request_rejected",
            message="The model provider rejected this operation.",
            kind=FailureKind.DEPENDENCY_FAILURE,
            details={"stage": stage},
            retryable=False,
        )
    if isinstance(error, LLMUsageSettlementError):
        return AppError(
            code="llm_usage_settlement_failed",
            message="Model usage could not be recorded safely.",
            kind=FailureKind.UNAVAILABLE,
            details={"stage": stage},
            retryable=True,
        )
    return AppError(
        code="llm_operation_failed",
        message="The model operation failed unexpectedly.",
        kind=FailureKind.DEPENDENCY_FAILURE,
        details={"stage": stage},
        retryable=True,
    )
