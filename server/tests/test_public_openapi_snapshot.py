from __future__ import annotations

import json
from pathlib import Path

from app.scripts.export_public_openapi import OUTPUT, public_openapi_schema


def test_public_openapi_contains_only_public_v1_routes() -> None:
    schema = public_openapi_schema()
    assert schema["paths"]
    assert all(path.startswith("/api/v1") for path in schema["paths"])


def test_public_openapi_declares_auth_failure_contract() -> None:
    schema = public_openapi_schema()
    assert "ApiErrorResponse" in schema["components"]["schemas"]
    login_responses = schema["paths"]["/api/v1/auth/login"]["post"]["responses"]
    refresh_responses = schema["paths"]["/api/v1/auth/refresh"]["post"]["responses"]
    assert {"401", "422", "429", "503"}.issubset(login_responses)
    assert {"401", "503"}.issubset(refresh_responses)
    assert login_responses["401"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ApiErrorResponse"
    }


def test_public_openapi_snapshot_is_current() -> None:
    committed = json.loads(Path(OUTPUT).read_text(encoding="utf-8"))
    assert committed == public_openapi_schema()
