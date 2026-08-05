"""Export the deterministic public v1 OpenAPI contract for web clients."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

# Schema export never performs live provider calls, but composition imports
# validate that provider configuration exists. Stable sentinels keep export
# deterministic without reading developer secrets.
os.environ.setdefault("DEEPSEEK_API_KEY", "openapi-export")
os.environ.setdefault("STRIPE_API_KEY", "sk_openapi_export")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_openapi_export")
os.environ.setdefault("STRIPE_MONTHLY_PRICE_ID", "price_openapi_monthly")
os.environ.setdefault("STRIPE_YEARLY_PRICE_ID", "price_openapi_yearly")

from app.main import app
from app.transport.http.errors import ApiErrorResponse

PUBLIC_PREFIX = "/api/v1"
OUTPUT = Path(__file__).resolve().parents[2] / "openapi" / "public-v1.json"

_AUTH_FAILURES: dict[str, dict[str, tuple[int, ...]]] = {
    "/api/v1/auth/login": {"post": (401, 422, 429, 503)},
    "/api/v1/auth/register": {"post": (422, 429, 503)},
    "/api/v1/auth/verify-email": {"post": (400, 422, 503)},
    "/api/v1/auth/resend-verification": {"post": (422, 429, 503)},
    "/api/v1/auth/forgot-password": {"post": (422, 429, 503)},
    "/api/v1/auth/reset-password": {"post": (400, 422, 429, 503)},
    "/api/v1/auth/refresh": {"post": (401, 503)},
    "/api/v1/auth/logout": {"post": (401, 503)},
    "/api/v1/auth/change-password": {"post": (400, 401, 422, 503)},
    "/api/v1/me": {"get": (401, 503)},
}

_STATUS_DESCRIPTIONS = {
    400: "Invalid or expired authentication token",
    401: "Authentication failed or session unavailable",
    422: "Request validation failed",
    429: "Authentication rate limit exceeded",
    503: "Authentication service unavailable",
}


def _install_api_error_schema(schema: dict[str, Any]) -> None:
    model_schema = ApiErrorResponse.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )
    definitions = model_schema.pop("$defs", {})
    schemas = schema.setdefault("components", {}).setdefault("schemas", {})
    schemas.update(definitions)
    schemas["ApiErrorResponse"] = model_schema


def _install_auth_failure_responses(schema: dict[str, Any]) -> None:
    _install_api_error_schema(schema)
    response_schema = {"$ref": "#/components/schemas/ApiErrorResponse"}
    for path, operations in _AUTH_FAILURES.items():
        path_item = schema.get("paths", {}).get(path)
        if not path_item:
            continue
        for method, statuses in operations.items():
            operation = path_item.get(method)
            if not operation:
                continue
            responses = operation.setdefault("responses", {})
            for status in statuses:
                responses[str(status)] = {
                    "description": _STATUS_DESCRIPTIONS[status],
                    "content": {
                        "application/json": {"schema": response_schema},
                    },
                }


def public_openapi_schema() -> dict[str, Any]:
    # FastAPI caches and returns the same dictionary instance. Export filtering
    # must never mutate the live application's schema in this process.
    schema = deepcopy(app.openapi())
    schema["paths"] = {
        path: schema["paths"][path]
        for path in sorted(schema.get("paths", {}))
        if path.startswith(PUBLIC_PREFIX)
    }
    _install_auth_failure_responses(schema)
    return schema


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(public_openapi_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
