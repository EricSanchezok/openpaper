"""Bounded transport-edge normalization for ephemeral client IP values."""

from __future__ import annotations

from ipaddress import ip_address

from starlette.requests import Request

UNKNOWN_CLIENT_IP = "unknown"
MAX_CLIENT_IP_LENGTH = 64


def normalize_client_ip(value: object | None) -> str:
    """Return one canonical IP scalar without preserving arbitrary peer input."""
    if not isinstance(value, str):
        return UNKNOWN_CLIENT_IP
    candidate = value.strip()
    if not candidate or len(candidate) > MAX_CLIENT_IP_LENGTH:
        return UNKNOWN_CLIENT_IP
    try:
        normalized = str(ip_address(candidate))
    except ValueError:
        return UNKNOWN_CLIENT_IP
    if len(normalized) > MAX_CLIENT_IP_LENGTH:
        return UNKNOWN_CLIENT_IP
    return normalized


def http_client_ip(request: Request) -> str:
    """Extract and normalize the directly connected HTTP peer."""
    return normalize_client_ip(request.client.host if request.client else None)


__all__ = [
    "MAX_CLIENT_IP_LENGTH",
    "UNKNOWN_CLIENT_IP",
    "http_client_ip",
    "normalize_client_ip",
]
