"""Canonical non-sensitive references for signed internal deliveries."""

from app.shared.application.canonical_digest import canonical_sha256

JOB_DELIVERY_REFERENCE_DOMAIN = "scholens.job.delivery_ref.v1"


def job_delivery_reference(delivery_id: str) -> str:
    if not delivery_id or len(delivery_id) > 128:
        raise ValueError("Job delivery ID is invalid")
    return canonical_sha256(JOB_DELIVERY_REFERENCE_DOMAIN, delivery_id)


__all__ = ["JOB_DELIVERY_REFERENCE_DOMAIN", "job_delivery_reference"]
