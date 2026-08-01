"""OpenTelemetry configuration and safe custom spans."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from threading import Lock
from time import monotonic
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import (
    Decision,
    ParentBased,
    Sampler,
    SamplingResult,
    TraceIdRatioBased,
)

_LOCK = Lock()
_CONFIGURED = False
_TRACER_PROVIDER: TracerProvider | None = None
_METER_PROVIDER: MeterProvider | None = None


class _ReservoirRatioSampler(Sampler):
    """Sample one root trace per second plus a stable ratio of the remainder."""

    def __init__(self, ratio: float) -> None:
        self._ratio_sampler = TraceIdRatioBased(ratio)
        self._lock = Lock()
        self._reservoir_second: int | None = None

    def should_sample(
        self,
        parent_context: Any,
        trace_id: int,
        name: str,
        kind: Any = None,
        attributes: Any = None,
        links: Any = None,
        trace_state: Any = None,
    ) -> SamplingResult:
        current_second = int(monotonic())
        with self._lock:
            if self._reservoir_second != current_second:
                self._reservoir_second = current_second
                return SamplingResult(
                    Decision.RECORD_AND_SAMPLE,
                    attributes=attributes,
                    trace_state=trace_state,
                )
        return self._ratio_sampler.should_sample(
            parent_context,
            trace_id,
            name,
            kind,
            attributes,
            links,
            trace_state,
        )

    def get_description(self) -> str:
        return "ReservoirRatioSampler{1/sec+10%}"


def configure_telemetry(
    *,
    service: str,
    environment: str,
    release: str | None,
    endpoint: str | None,
) -> None:
    global _CONFIGURED, _TRACER_PROVIDER, _METER_PROVIDER
    if endpoint is None:
        return
    with _LOCK:
        if _CONFIGURED:
            return
        resource = Resource.create(
            {
                "service.name": service,
                "deployment.environment.name": environment,
                "service.version": release or "development",
            }
        )
        tracer_provider = TracerProvider(
            resource=resource,
            sampler=ParentBased(root=_ReservoirRatioSampler(0.1)),
        )
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
        )
        metric_reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=endpoint, insecure=True)
        )
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        trace.set_tracer_provider(tracer_provider)
        metrics.set_meter_provider(meter_provider)
        _TRACER_PROVIDER = tracer_provider
        _METER_PROVIDER = meter_provider
        _CONFIGURED = True


@contextmanager
def instrumented_span(
    name: str,
    *,
    attributes: Mapping[str, str | int | float | bool] | None = None,
) -> Iterator[trace.Span]:
    tracer = trace.get_tracer("scholens")
    with tracer.start_as_current_span(name, attributes=dict(attributes or {})) as span:
        yield span


def shutdown_telemetry() -> None:
    if _TRACER_PROVIDER is not None:
        _TRACER_PROVIDER.shutdown()
    if _METER_PROVIDER is not None:
        _METER_PROVIDER.shutdown()
