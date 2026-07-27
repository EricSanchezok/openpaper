"""Stable, non-secret configuration for Server test imports."""

import os

os.environ.setdefault("DEEPSEEK_API_KEY", "test-deepseek-key")
os.environ.setdefault("STRIPE_API_KEY", "sk_test_scholens")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_scholens")
os.environ.setdefault("STRIPE_MONTHLY_PRICE_ID", "price_test_monthly")
os.environ.setdefault("STRIPE_YEARLY_PRICE_ID", "price_test_yearly")
