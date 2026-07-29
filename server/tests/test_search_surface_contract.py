"""Contracts for the intentionally narrow external-research surface."""

from app.main import app


def test_discovery_and_private_search_have_distinct_stable_namespaces() -> None:
    paths = set(app.openapi()["paths"])

    assert "/api/v1/discovery/papers/match" in paths
    assert "/api/v1/discovery/papers/search" in paths
    assert "/api/v1/discovery/papers/authors" in paths
    assert "/api/v1/search/papers" in paths
    assert "/api/v1/search/research" in paths
    assert not any(path.startswith("/api/v1/search/global") for path in paths)
    assert not any(path.startswith("/api/v1/search/local") for path in paths)
