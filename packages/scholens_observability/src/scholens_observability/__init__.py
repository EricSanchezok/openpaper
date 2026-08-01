"""Business-agnostic observability primitives shared by Scholens services."""

from .context import (
    ObservabilityContext,
    bind_context,
    current_context,
    reset_context,
    set_context,
    update_context,
)
from .diagnostics import (
    BufferedS3DiagnosticSnapshotRecorder,
    DiagnosticSnapshot,
    DiagnosticSnapshotRecorder,
    NullDiagnosticSnapshotRecorder,
    SensitiveValue,
    build_snapshot,
    diagnostic_id,
    should_sample_success,
)
from .logging import configure_logging, log_event
from .metrics import add_counter, record_histogram
from .tracing import configure_telemetry, instrumented_span, shutdown_telemetry

__all__ = [
    "DiagnosticSnapshot",
    "BufferedS3DiagnosticSnapshotRecorder",
    "DiagnosticSnapshotRecorder",
    "NullDiagnosticSnapshotRecorder",
    "ObservabilityContext",
    "SensitiveValue",
    "add_counter",
    "bind_context",
    "build_snapshot",
    "configure_logging",
    "configure_telemetry",
    "current_context",
    "diagnostic_id",
    "instrumented_span",
    "log_event",
    "record_histogram",
    "reset_context",
    "set_context",
    "should_sample_success",
    "shutdown_telemetry",
    "update_context",
]
