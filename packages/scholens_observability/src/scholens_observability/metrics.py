"""Low-cardinality OpenTelemetry metric helpers."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache

from opentelemetry import metrics


@lru_cache(maxsize=128)
def _counter(name: str):  # type: ignore[no-untyped-def]
    return metrics.get_meter("scholens").create_counter(name)


@lru_cache(maxsize=128)
def _histogram(name: str, unit: str):  # type: ignore[no-untyped-def]
    return metrics.get_meter("scholens").create_histogram(name, unit=unit)


def add_counter(
    name: str,
    value: int = 1,
    *,
    attributes: Mapping[str, str | int | float | bool] | None = None,
) -> None:
    _counter(name).add(value, attributes=dict(attributes or {}))


def record_histogram(
    name: str,
    value: int | float,
    *,
    unit: str = "ms",
    attributes: Mapping[str, str | int | float | bool] | None = None,
) -> None:
    _histogram(name, unit).record(value, attributes=dict(attributes or {}))
