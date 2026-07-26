"""Contracts for the intentionally narrow external-research surface."""

from app.main import app


def test_global_discovery_api_is_removed_but_citation_graph_remains() -> None:
    paths = set(app.openapi()["paths"])

    assert not any(path.startswith("/api/discover") for path in paths)
    assert "/api/search/global/search" not in paths
    assert "/api/search/global/match" in paths
    assert "/api/search/global/author" in paths
