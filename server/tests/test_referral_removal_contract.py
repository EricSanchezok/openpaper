"""Contracts that keep referral rewards and acquisition tracking removed."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.transport.http.public_v1.billing import checkout
from app.transport.http.public_v1.billing.config import SubscriptionInterval
from app.database.models import Base, Onboarding, UserProfile
from app.main import app
from sqlalchemy.orm import Session

ROOT = Path(__file__).parents[2]


def test_referral_routes_and_persistence_are_absent() -> None:
    paths = set(app.openapi()["paths"])
    table_names = set(Base.metadata.tables)

    assert not any(path.startswith("/api/referral") for path in paths)
    assert not any("referral-settle" in path for path in paths)
    assert "scholens.referral_codes" not in table_names
    assert "scholens.referrals" not in table_names
    assert not hasattr(UserProfile, "referral_toast_seen_at")
    assert not hasattr(Onboarding, "referral_source")
    assert not hasattr(Onboarding, "referral_source_other")


def test_initial_baseline_contains_no_referral_schema() -> None:
    baseline = next((ROOT / "server" / "migrations" / "versions").glob("*.py"))
    source = baseline.read_text(encoding="utf-8").lower()

    assert "referral_codes" not in source
    assert "referrals" not in source
    assert "referral_source" not in source
    assert "referral_toast_seen_at" not in source


def test_checkout_keeps_generic_promotion_codes_without_referral_discount() -> None:
    db = MagicMock(spec=Session)
    user = SimpleNamespace(id=7, email="user@example.com", display_name="User")
    stripe_customer = SimpleNamespace(id="cus_test")
    stripe_session = SimpleNamespace(client_secret="secret")

    with (
        patch.object(checkout, "MONTHLY_PRICE_ID", "price_monthly"),
        patch.object(
            checkout.subscription_crud,
            "get_by_user_id",
            return_value=None,
        ),
        patch.object(checkout.subscription_crud, "create_or_update"),
        patch.object(
            checkout.stripe.Customer,
            "create",
            return_value=stripe_customer,
        ),
        patch.object(
            checkout.stripe.checkout.Session,
            "create",
            return_value=stripe_session,
        ) as create_session,
        patch.object(checkout, "track_event"),
    ):
        result = checkout.create_checkout_session(
            interval=SubscriptionInterval.MONTHLY,
            db=db,
            current_user=user,
        )

    assert result == {"client_secret": "secret"}
    params = create_session.call_args.kwargs
    assert params["allow_promotion_codes"] is True
    assert "discounts" not in params
    assert "metadata" not in params
