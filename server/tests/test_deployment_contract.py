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


def test_single_baseline_preserves_non_orm_search_triggers() -> None:
    versions = sorted((ROOT / "server" / "migrations" / "versions").glob("*.py"))

    assert len(versions) == 1
    baseline = versions[0].read_text(encoding="utf-8")
    assert "down_revision: Union[str, None] = None" in baseline
    assert "scholens.paper_content_trigger" in baseline
    assert "scholens.paper_passages_tsvector_trigger" in baseline
    assert "ON scholens.papers" in baseline
    assert "ON scholens.paper_passages" in baseline


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
