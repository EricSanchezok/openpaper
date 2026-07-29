"""Executable dependency rules for the modular backend architecture."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from app.main import app
from app.transport.http.internal_v1.jobs_callbacks import webhook_router
from fastapi import FastAPI

ROOT = Path(__file__).parents[2]
APP_ROOT = ROOT / "server" / "app"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_domain_and_application_contracts_are_framework_independent() -> None:
    forbidden_roots = {
        "fastapi",
        "sqlalchemy",
        "boto3",
        "stripe",
        "requests",
        "requests_oauthlib",
        "cloud_auth",
    }
    contract_roots = [
        APP_ROOT / "shared" / "domain",
        APP_ROOT / "shared" / "application",
        APP_ROOT / "modules",
    ]
    violations: list[str] = []
    for root in contract_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "infrastructure" in path.parts:
                continue
            for imported in _imports(path):
                if imported.split(".", 1)[0] in forbidden_roots:
                    violations.append(
                        f"{path.relative_to(APP_ROOT)} imports {imported}"
                    )
    assert violations == []


def test_only_versioned_public_routes_are_exposed() -> None:
    paths = set(app.openapi()["paths"])
    public_business_paths = {path for path in paths if path.startswith("/api/")}
    assert public_business_paths
    assert all(path.startswith("/api/v1/") for path in public_business_paths)
    assert not any(path.startswith("/internal/") for path in paths)
    assert "/webhooks/v1/stripe" in paths


def test_jobs_use_one_generic_versioned_lifecycle_surface() -> None:
    internal = FastAPI()
    internal.include_router(webhook_router, prefix="/internal/v1")
    paths = set(internal.openapi()["paths"])

    assert {
        "/internal/v1/jobs/{job_id}/claim",
        "/internal/v1/jobs/{job_id}/heartbeat",
        "/internal/v1/jobs/{job_id}/complete",
        "/internal/v1/jobs/{job_id}/fail",
    } <= paths
    operation_suffixes = {
        "pdf-postprocess",
        "document-gc",
        "storage-delete",
        "zotero-postprocess",
        "audio",
        "data-table",
    }
    assert not any(
        path.rsplit("/", 1)[-1] in operation_suffixes for path in paths
    )


def test_public_openapi_surface_matches_reviewed_v1_contract() -> None:
    specification = app.openapi()
    actual = {
        "info": {
            "title": specification["info"]["title"],
            "version": specification["info"]["version"],
        },
        "paths": {
            path: sorted(
                method
                for method in operations
                if method in {"get", "post", "put", "patch", "delete"}
            )
            for path, operations in sorted(specification["paths"].items())
        },
    }
    expected = json.loads(
        (ROOT / "server" / "openapi" / "v1-contract.json").read_text(
            encoding="utf-8"
        )
    )
    assert actual == expected
