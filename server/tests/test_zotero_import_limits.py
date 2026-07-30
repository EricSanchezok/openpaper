"""Billing quota boundary used by Zotero import planning."""

from unittest.mock import MagicMock, patch

import pytest

from app.database.models import SubscriptionPlan
from app.modules.billing.infrastructure.quotas import (
    get_remaining_paper_upload_slots,
)


@pytest.mark.parametrize(
    ("plan", "used", "expected"),
    [
        (SubscriptionPlan.BASIC, 5, 5),
        (SubscriptionPlan.BASIC, 10, 0),
        (SubscriptionPlan.BASIC, 15, 0),
        (SubscriptionPlan.RESEARCHER, 499, 1),
        (SubscriptionPlan.RESEARCHER, 500, 0),
    ],
)
def test_remaining_paper_upload_slots(
    plan: str,
    used: int,
    expected: int,
) -> None:
    actor = MagicMock(id=7)
    with (
        patch(
            "app.modules.billing.infrastructure.quotas.get_user_subscription_plan",
            return_value=plan,
        ),
        patch(
            "app.modules.billing.infrastructure.quotas.resource_usage_repository"
        ) as usage,
    ):
        usage.completed_reference_count.return_value = used
        assert get_remaining_paper_upload_slots(MagicMock(), actor) == expected
