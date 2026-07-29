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


def _runtime_imports(path: Path) -> set[str]:
    """Return imports outside TYPE_CHECKING-only ORM relationship blocks."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()

    def visit(statements: list[ast.stmt], *, type_checking: bool = False) -> None:
        for node in statements:
            guarded = type_checking or (
                isinstance(node, ast.If)
                and isinstance(node.test, ast.Name)
                and node.test.id == "TYPE_CHECKING"
            )
            if not guarded:
                if isinstance(node, ast.Import):
                    modules.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules.add(node.module)
            for field in ("body", "orelse"):
                nested = getattr(node, field, None)
                if isinstance(nested, list):
                    visit(nested, type_checking=guarded)

    visit(tree.body)
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


def test_repositories_never_commit_the_callers_transaction() -> None:
    violations: list[str] = []
    for path in (APP_ROOT / "modules").rglob("*repository.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "commit"
            ):
                violations.append(f"{path.relative_to(APP_ROOT)}:{node.lineno}")
    assert violations == []


def test_transport_only_depends_on_application_and_protocol_layers() -> None:
    forbidden_fragments = (
        ".infrastructure",
        "app.database.models",
        "app.helpers",
        "app.llm",
    )
    violations: list[str] = []
    for path in (APP_ROOT / "transport").rglob("*.py"):
        for imported in _imports(path):
            if any(fragment in imported for fragment in forbidden_fragments):
                violations.append(f"{path.relative_to(APP_ROOT)} imports {imported}")
    assert violations == []


def test_application_never_selects_infrastructure_adapters() -> None:
    violations: list[str] = []
    for path in (APP_ROOT / "modules").rglob("application/**/*.py"):
        for imported in _imports(path):
            if ".infrastructure" in imported:
                violations.append(f"{path.relative_to(APP_ROOT)} imports {imported}")
    assert violations == []


def test_modules_do_not_reach_into_another_modules_infrastructure() -> None:
    violations: list[str] = []
    modules_root = APP_ROOT / "modules"
    for path in modules_root.rglob("*.py"):
        owner = path.relative_to(modules_root).parts[0]
        for imported in _runtime_imports(path):
            if imported.startswith("app.bootstrap.adapters"):
                violations.append(
                    f"{path.relative_to(APP_ROOT)} imports composition adapter {imported}"
                )
            prefix = "app.modules."
            if not imported.startswith(prefix):
                continue
            imported_parts = imported.split(".")
            if (
                len(imported_parts) > 3
                and imported_parts[2] != owner
                and imported_parts[3] == "infrastructure"
            ):
                violations.append(f"{path.relative_to(APP_ROOT)} imports {imported}")
    assert violations == []


def test_explicit_commits_are_limited_to_owned_background_transactions() -> None:
    allowed = {
        "bootstrap/adapters/document_gc.py",
        "modules/billing/infrastructure/stripe_webhook_ledger.py",
        "modules/jobs/infrastructure/dispatcher.py",
    }
    violations: list[str] = []
    transaction_roots = (
        APP_ROOT / "modules",
        APP_ROOT / "bootstrap" / "adapters",
    )
    for path in (path for root in transaction_roots for path in root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "commit"
            for node in ast.walk(tree)
        ):
            continue
        relative = str(path.relative_to(APP_ROOT))
        if relative not in allowed:
            violations.append(relative)
    assert violations == []


def test_paper_agent_and_mcp_adapters_share_application_capabilities() -> None:
    agent = APP_ROOT / "transport" / "agent" / "paper_tools.py"
    mcp = APP_ROOT / "transport" / "mcp" / "papers.py"
    combined_imports = _imports(agent) | _imports(mcp)

    assert {
        "app.modules.papers.application.content",
        "app.modules.papers.application.search",
    } <= combined_imports
    assert all(".infrastructure" not in imported for imported in _imports(agent))
    for imported in _imports(mcp):
        assert ".infrastructure" not in imported
        assert not imported.startswith("app.transport.http")
        assert imported != "requests"


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
    assert "/internal/v1/schedules/zotero-sync" in paths
    operation_suffixes = {
        "pdf-postprocess",
        "document-gc",
        "storage-delete",
        "zotero-postprocess",
        "audio",
        "data-table",
    }
    assert not any(path.rsplit("/", 1)[-1] in operation_suffixes for path in paths)


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
        (ROOT / "server" / "openapi" / "v1-contract.json").read_text(encoding="utf-8")
    )
    assert actual == expected
