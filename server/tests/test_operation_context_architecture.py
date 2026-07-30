from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

from app.bootstrap.capabilities import ApplicationCapabilities
from app.database.models.tool_invocation import ToolInvocation
from app.modules.conversations.infrastructure.models import Message
from app.modules.integrations.zotero.infrastructure.models import (
    ZoteroOAuthPending,
)
from app.modules.jobs.infrastructure.models import DurableJob
from app.modules.operation_journal.infrastructure.models import (
    OperationJournalEntryModel,
)
from app.shared.application.operation_context import (
    OperationContext,
    OperationContextFactory,
)

ROOT = Path(__file__).parents[2]
APP_ROOT = ROOT / "server" / "app"
MIGRATIONS_ROOT = ROOT / "server" / "migrations" / "versions"

_PROVENANCE_DECISION_FIELDS = {"origin", "credential", "initiated_by"}
_JOURNAL_METHODS = {"append", "append_many"}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(path: Path) -> set[str]:
    tree = _tree(path)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _imported_symbols(path: Path) -> set[str]:
    symbols: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom):
            symbols.update(alias.name for alias in node.names)
    return symbols


def _python_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)
    )


def _attribute_parts(node: ast.expr) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        return (*_attribute_parts(node.value), node.attr)
    return ()


def _imports_operation_context(path: Path) -> bool:
    return (
        "OperationContext" in _imported_symbols(path)
        or "app.shared.application.operation_context" in _imports(path)
        or any(
            isinstance(node, ast.Attribute) and node.attr == "OperationContext"
            for node in ast.walk(_tree(path))
        )
    )


def _operation_parameter_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for function in (
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        arguments = (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
        for argument in arguments:
            annotation = argument.annotation
            if annotation is None:
                continue
            if any(
                (isinstance(node, ast.Name) and node.id == "OperationContext")
                or (isinstance(node, ast.Attribute) and node.attr == "OperationContext")
                for node in ast.walk(annotation)
            ):
                names.add(argument.arg)
    return names


def _is_journal_call(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr not in _JOURNAL_METHODS:
        return False
    receiver = _attribute_parts(node.func.value)
    return any(part.strip("_").endswith("journal") for part in receiver)


def _created_table_columns() -> dict[str, set[str]]:
    tables: dict[str, set[str]] = {}
    for path in _python_files(MIGRATIONS_ROOT):
        for node in ast.walk(_tree(path)):
            if (
                not isinstance(node, ast.Call)
                or not isinstance(node.func, ast.Attribute)
                or node.func.attr != "create_table"
                or not node.args
                or not isinstance(node.args[0], ast.Constant)
                or not isinstance(node.args[0].value, str)
            ):
                continue
            table_name = node.args[0].value
            columns = tables.setdefault(table_name, set())
            for argument in node.args[1:]:
                if (
                    isinstance(argument, ast.Call)
                    and isinstance(argument.func, ast.Attribute)
                    and argument.func.attr == "Column"
                    and argument.args
                    and isinstance(argument.args[0], ast.Constant)
                    and isinstance(argument.args[0].value, str)
                ):
                    columns.add(argument.args[0].value)
    return tables


def test_operation_context_is_framework_and_business_independent() -> None:
    path = APP_ROOT / "shared" / "application" / "operation_context.py"
    forbidden = (
        "app.modules",
        "app.tooling",
        "app.transport",
        "fastapi",
        "mcp",
        "pydantic",
        "sqlalchemy",
    )
    assert {
        imported for imported in _imports(path) if imported.startswith(forbidden)
    } == set()

    context_fields = {field.name for field in fields(OperationContext)}
    assert context_fields == {"trace", "initiated_by", "origin", "credential"}
    assert not hasattr(OperationContextFactory, "for_http")
    assert not hasattr(OperationContextFactory, "for_mcp")
    assert not hasattr(OperationContextFactory, "for_job")


def test_journal_is_private_and_schema_has_only_safe_projection() -> None:
    assert not hasattr(ApplicationCapabilities, "operation_journal")
    columns = set(OperationJournalEntryModel.__table__.c.keys())
    assert columns == {
        "entry_id",
        "operation_id",
        "correlation_id",
        "causation_id",
        "actor_id",
        "initiated_by",
        "origin_kind",
        "origin_name",
        "origin_reference",
        "credential_kind",
        "credential_id",
        "request_id",
        "conversation_id",
        "turn_id",
        "job_id",
        "action",
        "resources",
        "created_at",
        "updated_at",
    }
    assert {
        "payload",
        "metadata",
        "client_ip",
        "access_token",
        "secret",
    }.isdisjoint(columns)


def test_journal_store_has_no_commit_or_read_surface() -> None:
    path = APP_ROOT / "modules" / "operation_journal" / "infrastructure" / "store.py"
    source = path.read_text(encoding="utf-8")
    assert ".commit(" not in source
    assert ".execute(" not in source
    assert "select(" not in source
    assert "query" not in source.casefold()


def test_domain_and_persistence_layers_do_not_import_operation_context() -> None:
    offenders: list[str] = []
    for path in _python_files(APP_ROOT):
        relative = path.relative_to(APP_ROOT)
        is_domain = "domain" in relative.parts
        is_infrastructure = "infrastructure" in relative.parts
        is_repository = "repository" in path.stem
        is_orm_model = path.name == "models.py" or relative.parts[:2] == (
            "database",
            "models",
        )
        if (
            is_domain or is_infrastructure or is_repository or is_orm_model
        ) and _imports_operation_context(path):
            offenders.append(str(relative))

    assert offenders == []


def test_application_does_not_use_provenance_as_a_business_input() -> None:
    offenders: list[str] = []
    application_files = tuple(
        path
        for path in _python_files(APP_ROOT / "modules")
        if "application" in path.relative_to(APP_ROOT).parts
    )
    for path in application_files:
        if "operation_journal" in path.parts:
            continue
        tree = _tree(path)
        context_parameter_names = _operation_parameter_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            parts = _attribute_parts(node)
            if not parts or parts[-1] not in _PROVENANCE_DECISION_FIELDS:
                continue
            roots = {part.strip("_") for part in parts[:-1]}
            if {
                "operation",
                "context",
                "operation_context",
            } & roots or context_parameter_names & set(parts[:-1]):
                offenders.append(f"{path.relative_to(APP_ROOT)}:{node.lineno}")

    assert offenders == []


def test_only_application_services_call_operation_journal() -> None:
    call_offenders: list[str] = []
    import_offenders: list[str] = []
    for path in _python_files(APP_ROOT):
        relative = path.relative_to(APP_ROOT)
        is_application_service = (
            "modules" in relative.parts and "application" in relative.parts
        )
        if not is_application_service:
            for node in ast.walk(_tree(path)):
                if isinstance(node, ast.Call) and _is_journal_call(node):
                    call_offenders.append(f"{relative}:{node.lineno}")

        is_forbidden_consumer = (
            relative.parts[0] in {"tooling", "transport"}
            or "adapters" in relative.parts
            or "infrastructure" in relative.parts
            or "repository" in path.stem
            or path.name == "models.py"
        )
        if (
            is_forbidden_consumer
            and "operation_journal" not in relative.parts
            and "app.modules.operation_journal.application" in _imports(path)
        ):
            import_offenders.append(str(relative))

    assert call_offenders == []
    assert import_offenders == []


def test_causality_models_use_only_the_final_schema() -> None:
    expected_columns = {
        DurableJob: {"correlation_id", "origin_operation_id"},
        Message: {"turn_id", "created_operation_id", "correlation_id"},
        ZoteroOAuthPending: {"correlation_id", "origin_operation_id"},
        ToolInvocation: {"operation_id"},
    }
    for model, expected in expected_columns.items():
        columns = model.__table__.c
        assert expected <= set(columns.keys())
        assert all(columns[name].nullable is False for name in expected)

    tool_columns = set(ToolInvocation.__table__.c.keys())
    assert {"source", "access_key_id"}.isdisjoint(tool_columns)


def test_migrations_define_only_final_operation_causality() -> None:
    migration_paths = _python_files(MIGRATIONS_ROOT)
    assert all("2200" not in path.name for path in migration_paths)

    tables = _created_table_columns()
    assert {"correlation_id", "origin_operation_id"} <= tables["jobs"]
    assert {
        "turn_id",
        "created_operation_id",
        "correlation_id",
    } <= tables["messages"]
    assert {"operation_id"} <= tables["tool_invocations"]
    assert {"source", "access_key_id"}.isdisjoint(tables["tool_invocations"])


def test_adapters_do_not_define_inline_operation_actions() -> None:
    adapter_files = {
        *_python_files(APP_ROOT / "bootstrap" / "adapters"),
        *(
            path
            for path in _python_files(APP_ROOT / "modules")
            if "infrastructure" in path.relative_to(APP_ROOT).parts
        ),
    }
    offenders: list[str] = []
    for path in sorted(adapter_files):
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Call):
                continue
            function_name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else (node.func.attr if isinstance(node.func, ast.Attribute) else None)
            )
            if function_name == "OperationAction":
                offenders.append(f"{path.relative_to(APP_ROOT)}:{node.lineno}")

    assert offenders == []


def test_external_workflows_do_not_own_database_sessions() -> None:
    offenders: list[str] = []
    for path in _python_files(APP_ROOT / "bootstrap" / "workflows"):
        imports = _imports(path)
        imported_symbols = _imported_symbols(path)
        if any(module.startswith("sqlalchemy") for module in imports):
            offenders.append(f"{path.relative_to(APP_ROOT)}:sqlalchemy")
        if {"Session", "sessionmaker"} & imported_symbols:
            offenders.append(f"{path.relative_to(APP_ROOT)}:Session")

        for node in ast.walk(_tree(path)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"commit", "rollback"}
            ):
                offenders.append(f"{path.relative_to(APP_ROOT)}:{node.lineno}")
            elif isinstance(node, ast.Name) and node.id in {"Session", "sessionmaker"}:
                offenders.append(f"{path.relative_to(APP_ROOT)}:{node.lineno}")

    assert offenders == []
