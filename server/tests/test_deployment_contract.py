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

    assert services["client"]["networks"] == {
        "edge": {"aliases": ["openpaper-client"]}
    }
    assert services["api"]["networks"]["edge"] == {
        "aliases": ["openpaper-api"]
    }
    for service in ("jobs-api", "worker", "beat", "rabbitmq", "redis", "migrate"):
        assert "edge" not in services[service]["networks"]
    assert compose["networks"]["internal"]["internal"] is True
    assert compose["networks"]["edge"]["external"] is True
    assert all("ports" not in service for service in services.values())


def test_release_images_are_required_and_runtime_containers_are_non_root() -> None:
    compose_text = (PRODUCTION / "compose.yaml").read_text(encoding="utf-8")
    for variable in (
        "OPENPAPER_API_IMAGE",
        "OPENPAPER_CLIENT_IMAGE",
        "OPENPAPER_JOBS_IMAGE",
    ):
        assert f"${{{variable}:?" in compose_text

    for dockerfile in ("server/Dockerfile", "client/Dockerfile", "jobs/Dockerfile"):
        content = (ROOT / dockerfile).read_text(encoding="utf-8")
        assert re.search(r"^USER (?!root$).+", content, re.MULTILINE)

    assert "HEALTHCHECK" in (ROOT / "server" / "Dockerfile").read_text(encoding="utf-8")
    assert "HEALTHCHECK" in (ROOT / "client" / "Dockerfile").read_text(encoding="utf-8")
    assert "healthcheck:" in compose_text


def test_database_contract_shares_auth_and_isolates_openpaper() -> None:
    runtime = (PRODUCTION / "runtime.env.example").read_text(encoding="utf-8")
    bootstrap = (PRODUCTION / "bootstrap-db.sql").read_text(encoding="utf-8")

    assert runtime.count("search_path%3Dopenpaper%2Cauth%2Cpublic") == 2
    assert "CREATE SCHEMA IF NOT EXISTS auth" in bootstrap
    assert "CREATE SCHEMA IF NOT EXISTS openpaper" in bootstrap
    assert "GRANT CREATE ON DATABASE %I TO %I" in bootstrap
    assert 'REVOKE CREATE ON SCHEMA auth, openpaper, public FROM :"app_role"' in bootstrap
    assert "ALTER DEFAULT PRIVILEGES" in bootstrap


def test_caddy_contract_hides_internal_health_and_routes_same_origin_api() -> None:
    caddy = (PRODUCTION / "Caddyfile.snippet").read_text(encoding="utf-8")

    assert "{$OPENPAPER_DOMAIN}" in caddy
    assert "respond @internal_health 404" in caddy
    assert "reverse_proxy openpaper-api:8000" in caddy
    assert "reverse_proxy openpaper-client:3000" in caddy


def test_ci_builds_images_and_runs_unified_migrations_twice() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "tags: openpaper-api:ci" in workflow
    assert "for _ in 1 2; do" in workflow
    assert "python -m app.scripts.migrate_all" in workflow
    assert "OPENPAPER_DB_SCHEMA=openpaper" in workflow
    assert "CREATE TABLE openpaper.must_not_create" in workflow


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
