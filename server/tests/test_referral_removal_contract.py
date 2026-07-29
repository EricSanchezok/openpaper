"""Contracts that keep referral rewards and acquisition tracking removed."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.database.models import Base, Onboarding, UserProfile
from app.main import app
from app.modules.billing.infrastructure import application_gateway
from app.modules.billing.infrastructure.application_gateway import (
    StripePaymentProvider,
)

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
    baseline = sorted((ROOT / "server" / "migrations" / "versions").glob("*.py"))[0]
    source = baseline.read_text(encoding="utf-8").lower()

    assert "referral_codes" not in source
    assert "referrals" not in source
    assert "referral_source" not in source
    assert "referral_toast_seen_at" not in source


def test_checkout_keeps_generic_promotion_codes_without_referral_discount() -> None:
    stripe_session = SimpleNamespace(
        id="cs_test", client_secret="secret", status="open"
    )

    with patch.object(
        application_gateway.stripe.checkout.Session,
        "create",
        return_value=stripe_session,
    ) as create_session:
        result = StripePaymentProvider().create_checkout_session(
            user_id=7,
            customer_id="cus_test",
            price_id="price_monthly",
        )

    assert result.client_secret == "secret"
    params = create_session.call_args.kwargs
    assert params["allow_promotion_codes"] is True
    assert "discounts" not in params
    assert "metadata" not in params
