"""Regression gates for domain concepts intentionally removed before launch."""

from pathlib import Path
import ast
import re

ROOT = Path(__file__).parents[2]
BUSINESS_ROOTS = (
    ROOT / "server" / "app",
    ROOT / "jobs" / "src",
    ROOT / "client" / "src",
)
HTTP_ROOT = ROOT / "server" / "app" / "transport" / "http"


def _http_route_paths() -> list[Path]:
    return [
        path
        for path in HTTP_ROOT.rglob("*.py")
        if path.name not in {"__init__.py", "auth_dependencies.py", "errors.py"}
    ]


def _business_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for root in BUSINESS_ROOTS
        for path in root.rglob("*")
        if path.suffix in {".py", ".ts", ".tsx"}
    )


def test_removed_domain_concepts_do_not_return() -> None:
    source = _business_source()
    forbidden = (
        "ProjectRoles",
        "ProjectRole",
        "ProjectAudioOverview",
        "PaperNote",
        "PaperImage",
        "_filter_by_user",
        "get_cached_presigned_url_by_owner",
        "cached_presigned_url",
        "presigned_url_expires_at",
        "BackgroundTasks",
        "paper_crud",
        "project_paper_crud",
        "paper_tag_crud",
        "message_crud",
    )
    for pattern in forbidden:
        assert pattern not in source


def test_old_ownership_and_shared_conversation_routes_do_not_return() -> None:
    source = _business_source()
    for route in (
        '"/api/paper"',
        '"/api/paper/upload"',
        '"/api/conversation/share',
        '"/api/projects/conversations',
    ):
        assert route not in source


def test_streaming_errors_never_expose_exception_text() -> None:
    source = _business_source()
    exposed_exception = re.compile(
        r"""["']content["']\s*:\s*str\((?:e|exc|error|exception)\)"""
    )
    assert exposed_exception.search(source) is None


def test_http_adapters_do_not_define_request_or_response_models() -> None:
    adapter_source = "\n".join(
        path.read_text(encoding="utf-8") for path in _http_route_paths()
    )
    assert re.search(r"^class\s+\w+\(BaseModel\)", adapter_source, re.MULTILINE) is None


def test_http_adapters_do_not_own_broad_exception_boundaries() -> None:
    violations: list[str] = []
    for path in _http_route_paths():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id == "Exception"
            ):
                violations.append(f"{path.relative_to(HTTP_ROOT)}:{node.lineno}")
    assert violations == []


def test_http_adapters_use_the_stable_application_error_contract() -> None:
    adapter_source = "\n".join(
        path.read_text(encoding="utf-8") for path in _http_route_paths()
    )
    assert "HTTPException" not in adapter_source
