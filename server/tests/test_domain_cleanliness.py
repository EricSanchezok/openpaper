"""Regression gates for domain concepts intentionally removed before launch."""

from pathlib import Path

ROOT = Path(__file__).parents[2]
BUSINESS_ROOTS = (
    ROOT / "server" / "app",
    ROOT / "jobs" / "src",
    ROOT / "client" / "src",
)


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
        "_filter_by_user",
        "get_cached_presigned_url_by_owner",
        "cached_presigned_url",
        "presigned_url_expires_at",
        "BackgroundTasks",
    )
    for pattern in forbidden:
        assert pattern not in source


def test_old_ownership_and_shared_conversation_routes_do_not_return() -> None:
    source = _business_source()
    for route in (
        '"/api/paper"',
        '"/api/conversation/share',
        '"/api/projects/conversations',
    ):
        assert route not in source
