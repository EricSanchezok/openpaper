"""Architecture gates for the single workspace-tool permission path."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.tooling.catalog import ToolCatalog

ROOT = Path(__file__).parents[2]
APP_ROOT = ROOT / "server" / "app"

_ACCESS_AWARE_CATALOG_METHODS = {
    "definitions_for",
    "provider_declarations",
    "definition_for",
    "is_available",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_workspace_permission_has_one_canonical_enum_definition() -> None:
    definitions: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ClassDef) and node.name == "WorkspacePermission":
                definitions.append(str(path.relative_to(APP_ROOT)))

    assert definitions == ["shared/domain/workspace_permissions.py"]


def test_catalog_exposes_only_access_aware_public_lookup_methods() -> None:
    public_methods = {
        name
        for name, value in ToolCatalog.__dict__.items()
        if callable(value) and not name.startswith("_")
    }
    assert _ACCESS_AWARE_CATALOG_METHODS <= public_methods
    assert "definition" not in public_methods

    for name in _ACCESS_AWARE_CATALOG_METHODS:
        parameters = list(inspect.signature(getattr(ToolCatalog, name)).parameters)
        assert parameters[:2] == ["self", "access"]


def test_catalog_consumers_never_use_profile_only_lookup_arguments() -> None:
    violations: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        for node in ast.walk(_tree(path)):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _ACCESS_AWARE_CATALOG_METHODS
            ):
                continue
            access_argument = (
                node.args[0]
                if node.args
                else next(
                    (
                        keyword.value
                        for keyword in node.keywords
                        if keyword.arg == "access"
                    ),
                    None,
                )
            )
            if (
                access_argument is None
                or (
                    isinstance(access_argument, ast.Constant)
                    and isinstance(access_argument.value, str)
                )
                or (
                    isinstance(access_argument, ast.Name)
                    and access_argument.id.endswith("_TOOL_PROFILE")
                )
            ):
                violations.append(
                    f"{path.relative_to(APP_ROOT)}:{node.lineno} "
                    f"calls {node.func.attr} without ToolAccess"
                )
    assert violations == []


def test_every_tool_dispatcher_consumer_passes_access_explicitly() -> None:
    violations: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "ToolDispatcher" not in source or "app.tooling" not in _imports(path):
            continue
        for node in ast.walk(_tree(path)):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "dispatch"
            ):
                continue
            if not any(keyword.arg == "access" for keyword in node.keywords):
                violations.append(
                    f"{path.relative_to(APP_ROOT)}:{node.lineno} dispatches "
                    "without ToolAccess"
                )
    assert violations == []


def test_mcp_transport_has_no_static_allowlist_or_permission_branching() -> None:
    path = APP_ROOT / "transport" / "mcp" / "server.py"
    source = path.read_text(encoding="utf-8")
    tree = _tree(path)

    assert "allowed_names" not in source
    assert ".required_permission" not in source
    assert "WorkspacePermission" not in source
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            permission_literals = {
                child.value
                for child in ast.walk(node.test)
                if isinstance(child, ast.Constant)
                and child.value in {"read", "write", "delete"}
            }
            assert permission_literals == set()
