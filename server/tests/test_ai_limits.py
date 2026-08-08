from app.helpers.ai_limits import AILimitExceeded, ai_limit_app_error
from app.shared.domain import FailureKind


def test_ai_limit_maps_real_quota_exhaustion_to_rate_limited() -> None:
    error = ai_limit_app_error(
        AILimitExceeded("rate_limit_exceeded"),
        exceeded_message="AI request limit exceeded",
    )

    assert error.code == "rate_limit_exceeded"
    assert error.message == "AI request limit exceeded"
    assert error.kind is FailureKind.RATE_LIMITED


def test_ai_limit_maps_redis_outage_to_unavailable() -> None:
    error = ai_limit_app_error(
        AILimitExceeded("concurrency_limit_unavailable"),
        exceeded_message="AI request limit exceeded",
    )

    assert error.code == "concurrency_limit_unavailable"
    assert error.message == "AI capacity checks are temporarily unavailable"
    assert error.kind is FailureKind.UNAVAILABLE
