"""Static contracts for the production deployment package."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
PRODUCTION = ROOT / "deploy" / "production"


def load_compose() -> dict[str, object]:
    return yaml.safe_load((PRODUCTION / "compose.yaml").read_text(encoding="utf-8"))


def test_only_public_application_edges_join_shared_network() -> None:
    compose = load_compose()
    services = compose["services"]

    assert services["client"]["networks"] == {"edge": {"aliases": ["scholens-client"]}}
    assert services["api"]["networks"]["edge"] == {"aliases": ["scholens-api"]}
    for service in ("jobs-api", "worker", "beat", "rabbitmq", "redis", "migrate"):
        assert "edge" not in services[service]["networks"]
    assert compose["networks"]["internal"]["internal"] is True
    assert compose["networks"]["edge"]["external"] is True
    assert all("ports" not in service for service in services.values())


def test_release_images_are_required_and_runtime_containers_are_non_root() -> None:
    compose_text = (PRODUCTION / "compose.yaml").read_text(encoding="utf-8")
    compose = load_compose()
    for variable in (
        "SCHOLENS_API_IMAGE",
        "SCHOLENS_CLIENT_IMAGE",
        "SCHOLENS_JOBS_IMAGE",
    ):
        assert f"${{{variable}:?" in compose_text

    for dockerfile in ("server/Dockerfile", "client/Dockerfile", "jobs/Dockerfile"):
        content = (ROOT / dockerfile).read_text(encoding="utf-8")
        assert re.search(r"^USER (?!root$).+", content, re.MULTILINE)

    assert "HEALTHCHECK" in (ROOT / "server" / "Dockerfile").read_text(encoding="utf-8")
    assert "HEALTHCHECK" in (ROOT / "client" / "Dockerfile").read_text(encoding="utf-8")
    assert "healthcheck:" in compose_text
    for service in ("rabbitmq", "redis"):
        assert re.fullmatch(
            r"[^\s]+@sha256:[0-9a-f]{64}", compose["services"][service]["image"]
        )


def test_database_contract_shares_auth_and_isolates_scholens() -> None:
    runtime = (PRODUCTION / "runtime.env.example").read_text(encoding="utf-8")
    bootstrap = (PRODUCTION / "bootstrap-db.sql").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert runtime.count("/sanchezcloud?") == 2
    assert "search_path" not in runtime
    assert "CREATE SCHEMA IF NOT EXISTS auth" in bootstrap
    assert "CREATE SCHEMA IF NOT EXISTS scholens" in bootstrap
    assert "GRANT CREATE ON DATABASE" not in bootstrap
    assert "auth_migrator_role" in bootstrap
    assert "product_migrator_role" in bootstrap
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE auth.users" in bootstrap
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE auth.users" not in bootstrap
    assert 'FOR ROLE :"auth_migrator_role"' not in bootstrap
    assert (
        'REVOKE CREATE ON SCHEMA auth FROM :"app_role", :"product_migrator_role"'
        in bootstrap
    )
    assert "ALTER DEFAULT PRIVILEGES" in bootstrap
    for current_table in (
        "scholens.documents",
        "scholens.library_papers",
        "scholens.projects",
        "scholens.project_collaborators",
        "scholens.project_papers",
    ):
        assert current_table in ci
    for removed_table in (
        "scholens.papers",
        "scholens.project",
        "scholens.project_role",
        "scholens.project_paper",
    ):
        assert not re.search(rf"{re.escape(removed_table)}(?![a-z_])", ci)


def test_environment_catalog_matches_shared_cloud_auth_conventions() -> None:
    catalog = (ROOT / ".env.example").read_text(encoding="utf-8")
    compose = (PRODUCTION / "compose.yaml").read_text(encoding="utf-8")
    runtime = (PRODUCTION / "runtime.env.example").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    for variable in (
        "DATABASE_URL",
        "AUTH_DATABASE_URL",
        "AUTH_JWT_SECRET",
        "AUTH_ACCOUNT_LOCKOUT_THRESHOLD",
        "AUTH_ACCOUNT_LOCKOUT_DURATION_MINUTES",
        "AUTH_ALIYUN_DM_ACCESS_KEY_ID",
        "AUTH_ALIYUN_DM_ACCESS_KEY_SECRET",
        "AUTH_ALIYUN_DM_ACCOUNT_NAME",
        "AUTH_ALIYUN_DM_FROM_ALIAS",
        "AUTH_ALIYUN_DM_REPLY_TO_ADDRESS",
        "ANYSEARCH_MCP_URL",
        "ANYSEARCH_API_KEY",
        "SCHOLIGHT_MCP_URL",
        "SCHOLIGHT_MCP_DELEGATION_JWT_SECRET",
        "DEEPSEEK_API_KEY",
        "MINERU_API_TOKEN",
        "MOSS_API_KEY",
        "MOSS_MAX_AUDIO_BYTES",
        "JOBS_WEBHOOK_SIGNING_SECRET",
        "NEXT_PUBLIC_API_URL",
    ):
        assert f"{variable}=" in catalog

    assert not (ROOT / "server" / ".env.example").exists()
    assert "SCHOLENS_AUTH_ACCOUNT_LOCKOUT_THRESHOLD=" in runtime
    assert "SCHOLENS_ALIYUN_DM_REPLY_TO_ADDRESS=" in runtime
    assert "AUTH_ACCOUNT_LOCKOUT_THRESHOLD:" in compose
    assert "AUTH_ALIYUN_DM_REPLY_TO_ADDRESS:" in compose
    assert "SCHOLENS_ANYSEARCH_API_KEY=" in runtime
    assert "SCHOLENS_SCHOLIGHT_MCP_DELEGATION_JWT_SECRET=" in runtime
    assert "SCHOLENS_DEEPSEEK_API_KEY=" in runtime
    assert "SCHOLENS_MINERU_API_TOKEN=" in runtime
    assert "SCHOLENS_MOSS_API_KEY=" in runtime
    assert "SCHOLENS_MOSS_MAX_AUDIO_BYTES=" in runtime
    assert "SCHOLENS_JOBS_WEBHOOK_SIGNING_SECRET=" in runtime
    assert "ANYSEARCH_MCP_URL:" in compose
    assert "SCHOLIGHT_MCP_URL:" in compose
    assert "MOSS_MAX_AUDIO_BYTES:" in compose
    assert "DEEPSEEK_STRUCTURED_RETRIES:" in compose
    for legacy_variable in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "SCHOLIGHT_ACCESS_KEY",
        "JOBS_INTERNAL_SECRET",
    ):
        assert legacy_variable not in catalog + runtime + compose + ci
    assert "EXA_API_KEY" not in catalog + runtime + compose
    assert "FIRECRAWL_API_KEY" not in catalog + runtime + compose


def test_environment_catalog_covers_code_and_compose_references() -> None:
    assignment = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)
    catalog_variables = set(
        assignment.findall((ROOT / ".env.example").read_text(encoding="utf-8"))
    )
    runtime_variables = set(
        assignment.findall(
            (PRODUCTION / "runtime.env.example").read_text(encoding="utf-8")
        )
    )

    code_patterns = (
        re.compile(r'(?:os\.getenv|os\.environ\.get)\(\s*["\']([A-Z][A-Z0-9_]*)'),
        re.compile(r'os\.environ\[\s*["\']([A-Z][A-Z0-9_]*)'),
        re.compile(r"process\.env\.([A-Z][A-Z0-9_]*)"),
    )
    code_variables: set[str] = set()
    for source_root in (
        ROOT / "server" / "app",
        ROOT / "jobs" / "src",
        ROOT / "client" / "src",
    ):
        for path in source_root.rglob("*"):
            if path.suffix not in {".py", ".js", ".mjs", ".ts", ".tsx"}:
                continue
            source = path.read_text(encoding="utf-8")
            for pattern in code_patterns:
                code_variables.update(pattern.findall(source))

    assert code_variables - {"NODE_ENV"} <= catalog_variables

    compose = (PRODUCTION / "compose.yaml").read_text(encoding="utf-8")
    compose_variables = set(re.findall(r"\$\{(SCHOLENS_[A-Z0-9_]+)", compose))
    generated_release_variables = {
        "SCHOLENS_API_IMAGE",
        "SCHOLENS_CLIENT_IMAGE",
        "SCHOLENS_JOBS_IMAGE",
    }
    assert compose_variables - generated_release_variables <= runtime_variables


def test_migration_chain_preserves_non_orm_search_triggers() -> None:
    versions = sorted((ROOT / "server" / "migrations" / "versions").glob("*.py"))

    assert len(versions) == 3
    baseline = versions[0].read_text(encoding="utf-8")
    identifier_migration = versions[1].read_text(encoding="utf-8")
    search_migration = versions[2].read_text(encoding="utf-8")
    assert "down_revision: str | None = None" in baseline
    assert "scholens.document_content_trigger" in baseline
    assert "scholens.paper_passages_tsvector_trigger" in baseline
    assert "ON scholens.documents" in baseline
    assert "ON scholens.paper_passages" in baseline
    assert 'down_revision: str | None = "a21f80661812"' in identifier_migration
    assert "document_passages_tsvector_trigger" in identifier_migration
    assert "document_passages_tsvectorupdate" in identifier_migration
    assert 'down_revision: str | None = "d9079f37cdb1"' in search_migration
    for field in ("title", "authors", "keywords", "abstract", "raw_content"):
        assert f"NEW.{field}" in search_migration
    assert "discover_searches" not in baseline + identifier_migration + search_migration


def test_global_discovery_surfaces_are_absent_from_client_sources() -> None:
    protected_routes = ROOT / "client" / "src" / "app" / "(main)" / "(protected)"
    assert not (protected_routes / "discover").exists()
    assert not (protected_routes / "finder").exists()

    product_surfaces = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "README.md",
            ROOT / "client" / "design.md",
            ROOT / "client" / "src" / "app" / "sitemap.ts",
            ROOT / "client" / "src" / "components" / "QuickActions.tsx",
            ROOT / "client" / "src" / "components" / "sidebar" / "navItems.ts",
            ROOT / "client" / "src" / "content" / "introducing.mdx",
            ROOT / "client" / "src" / "content" / "systematic_review.mdx",
            ROOT / "server" / "app" / "helpers" / "templates" / "project_invite.html",
        )
    )
    for removed_identifier in (
        "/discover",
        "/finder",
        "Discover Research",
        "Document Finder",
    ):
        assert removed_identifier not in product_surfaces


def test_server_keeps_the_typed_sqlalchemy_two_mainline() -> None:
    app_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "server" / "app").rglob("*.py")
    )
    model_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "server" / "app" / "database" / "models").glob("*.py")
    )
    pyproject = (ROOT / "server" / "pyproject.toml").read_text(encoding="utf-8")

    assert "db.query(" not in app_sources
    assert "type: ignore" not in app_sources
    assert re.search(r"\bColumn\(", model_sources) is None
    assert "sqlalchemy.ext.mypy.plugin" not in pyproject


def test_pdf_viewer_has_one_browser_only_loading_boundary() -> None:
    wrapper = (
        ROOT / "client" / "src" / "components" / "PdfHighlighterViewer.tsx"
    ).read_text(encoding="utf-8")
    implementation = (
        ROOT / "client" / "src" / "components" / "PdfHighlighterViewerClient.tsx"
    ).read_text(encoding="utf-8")
    package = (ROOT / "client" / "package.json").read_text(encoding="utf-8")
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert 'import("./PdfHighlighterViewerClient")' in wrapper
    assert "ssr: false" in wrapper
    assert "react-pdf-highlighter-extended" not in wrapper
    assert "react-pdf-highlighter-extended" in implementation
    assert '"predev": "node scripts/sync-pdf-worker.mjs"' in package
    assert "sync-pdf-worker.mjs && node scripts/generate-blog-metadata.mjs" in package
    assert "client/public/pdf.worker.mjs" in ignore


def test_caddy_contract_hides_internal_health_and_routes_same_origin_api() -> None:
    caddy = (PRODUCTION / "Caddyfile.snippet").read_text(encoding="utf-8")

    assert "{$SCHOLENS_DOMAIN}" in caddy
    assert "respond @internal_health 404" in caddy
    assert "reverse_proxy scholens-api:8000" in caddy
    assert "reverse_proxy scholens-client:3000" in caddy


def test_ci_builds_images_and_runs_independent_migrations_twice() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "tags: scholens-api:ci" in workflow
    assert "for _ in 1 2; do" in workflow
    assert "cloud-auth migrate" in workflow
    assert "python -m app.scripts.migrate_product" in workflow
    assert "uv run mypy app" in workflow
    assert "uv run mypy src" in workflow
    assert "uv run ruff format --check app tests migrations" in workflow
    assert "uv run ruff format --check src tests" in workflow
    assert "scholens-api:ci alembic check" in workflow
    assert "window is not defined|document is not defined" in workflow
    assert "CREATE TABLE auth.product_migrator_must_not_create" in workflow
    assert "CREATE TABLE scholens.auth_migrator_must_not_create" in workflow


def test_external_actions_are_pinned_to_full_commit_shas() -> None:
    action_reference = re.compile(r"^\s*uses:\s*([^\s]+)@([^\s#]+)", re.MULTILINE)
    for name in ("ci.yml", "release.yml"):
        workflow = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        for action, revision in action_reference.findall(workflow):
            if action.startswith("./"):
                continue
            assert re.fullmatch(r"[0-9a-f]{40}", revision), (
                f"{action}@{revision} is mutable"
            )
