import ast
from dataclasses import fields
from pathlib import Path

from app.database.models.tool_invocation import ToolInvocation
from app.tooling import ToolCallContext

ROOT = Path(__file__).parents[2]
APP_ROOT = ROOT / "server" / "app"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_access_key_application_is_transport_and_tooling_independent() -> None:
    application_root = APP_ROOT / "modules" / "access_keys" / "application"
    forbidden_prefixes = (
        "app.tooling",
        "app.transport",
        "fastapi",
        "mcp",
        "sqlalchemy",
    )
    violations = {
        str(path.relative_to(APP_ROOT)): sorted(
            imported
            for imported in _imports(path)
            if imported.startswith(forbidden_prefixes)
        )
        for path in application_root.rglob("*.py")
    }
    assert {path: imports for path, imports in violations.items() if imports} == {}


def test_mcp_has_no_cloud_auth_or_legacy_actor_authentication_path() -> None:
    execution = (APP_ROOT / "bootstrap" / "execution.py").read_text(encoding="utf-8")
    transport = (APP_ROOT / "transport" / "mcp" / "server.py").read_text(
        encoding="utf-8"
    )

    assert "authenticate_cloud_access_token" not in execution
    assert "AuthenticatedIdentity" not in execution
    assert "capabilities.access_keys.authenticate(token)" in execution
    assert "executor.command" in execution
    assert "_actor_context" not in transport
    assert "_tool_access_context" not in transport
    assert "AuthenticatedAccessKey" in transport


def test_access_key_identity_is_not_added_to_tool_or_invocation_storage() -> None:
    assert "access_key_id" not in {field.name for field in fields(ToolCallContext)}
    assert "access_key_id" not in ToolInvocation.__table__.c
