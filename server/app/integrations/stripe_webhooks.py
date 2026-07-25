"""Typed boundary around Stripe's untyped webhook constructor."""

from typing import cast

import stripe


def construct_stripe_event(
    payload: bytes,
    signature: str,
    secret: str,
) -> stripe.Event:
    return cast(
        stripe.Event,
        stripe.Webhook.construct_event(payload, signature, secret),
    )
