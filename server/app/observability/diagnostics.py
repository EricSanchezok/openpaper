"""Composition and typed capture for encrypted diagnostic snapshots."""

from __future__ import annotations

import logging
from typing import Any, cast
from uuid import UUID

import boto3
from app.bootstrap.settings import AppSettings
from fastapi import Request
from scholens_observability import (
    BufferedS3DiagnosticSnapshotRecorder,
    DiagnosticSnapshotRecorder,
    NullDiagnosticSnapshotRecorder,
    build_snapshot,
    current_context,
)

logger = logging.getLogger(__name__)


def create_diagnostic_snapshot_recorder(
    settings: AppSettings,
) -> DiagnosticSnapshotRecorder:
    if not settings.diagnostic_snapshot_bucket:
        if settings.environment.casefold() == "production":
            raise ValueError("DIAGNOSTIC_SNAPSHOT_BUCKET is required in production")
        return NullDiagnosticSnapshotRecorder()
    if not settings.diagnostic_snapshot_kms_key_id:
        if settings.environment.casefold() == "production":
            raise ValueError(
                "DIAGNOSTIC_SNAPSHOT_KMS_KEY_ID is required when snapshots are enabled"
            )
        logger.warning("diagnostic.snapshot.disabled_missing_kms_key")
        return NullDiagnosticSnapshotRecorder()
    return BufferedS3DiagnosticSnapshotRecorder(
        client=cast(Any, boto3.client("s3")),
        bucket=settings.diagnostic_snapshot_bucket,
        kms_key_id=settings.diagnostic_snapshot_kms_key_id,
    )


def record_http_diagnostic(
    request: Request,
    *,
    snapshot_id: UUID,
    reason: str,
    error_code: str,
    error_kind: str,
    status_code: int,
) -> None:
    """Capture only explicitly safe fields at the generic HTTP boundary."""

    settings: AppSettings = request.app.state.settings
    recorder: DiagnosticSnapshotRecorder = (
        request.app.state.diagnostic_snapshot_recorder
    )
    context = current_context()
    route = str(getattr(request.scope.get("route"), "path", request.url.path))
    snapshot = build_snapshot(
        snapshot_id=snapshot_id,
        service=context.service,
        environment=settings.environment,
        release=settings.release_sha,
        reason=reason,
        request_id=getattr(request.state, "request_id", context.request_id),
        operation_id=getattr(request.state, "operation_id", context.operation_id),
        correlation_id=getattr(
            request.state,
            "correlation_id",
            context.correlation_id,
        ),
        actor_id=getattr(request.state, "actor_id", context.actor_id),
        sections={
            "request": {
                "method": request.method,
                "route": route,
            },
            "failure": {
                "code": error_code,
                "kind": error_kind,
                "status_code": status_code,
                "stage": context.stage,
            },
        },
    )
    recorder.record(snapshot)


def close_diagnostic_snapshot_recorder(recorder: DiagnosticSnapshotRecorder) -> None:
    close = getattr(recorder, "close", None)
    if callable(close):
        close(timeout=5)
