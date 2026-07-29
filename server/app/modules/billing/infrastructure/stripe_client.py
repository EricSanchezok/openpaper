"""Typed boundary around Stripe's untyped webhook constructor."""

from collections.abc import Callable
from typing import cast

import stripe


def construct_stripe_event(
    payload: bytes,
    signature: str,
    secret: str,
) -> stripe.Event:
    constructor = cast(
        Callable[[bytes, str, str], stripe.Event],
        stripe.Webhook.construct_event,
    )
    return constructor(payload, signature, secret)
