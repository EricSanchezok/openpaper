from pathlib import Path

import pytest

from app.cli import require_local_database_url, require_local_server_address

ROOT = Path(__file__).resolve().parents[2]


def test_scholens_uses_registered_shared_local_ports() -> None:
    environment = (ROOT / ".env.example").read_text(encoding="utf-8")
    server_cli = (ROOT / "server/app/cli.py").read_text(encoding="utf-8")
    web_package = (ROOT / "web/package.json").read_text(encoding="utf-8")
    legacy_package = (ROOT / "client/package.json").read_text(encoding="utf-8")
    jobs_api = (ROOT / "jobs/scripts/start_api.sh").read_text(encoding="utf-8")
    jobs_compose = (ROOT / "jobs/compose.local.yaml").read_text(encoding="utf-8")

    assert "127.0.0.1:55432/sanchezcloud" in environment
    assert "HOST=127.0.0.1" in environment
    assert "PORT=7301" in environment
    assert "http://127.0.0.1:7300" in environment
    assert "http://127.0.0.1:7301" in environment
    assert "http://127.0.0.1:7302" in environment
    assert "127.0.0.1:55672" in environment
    assert "127.0.0.1:56379" in environment
    assert "migrate_product()" not in server_cli
    assert 'os.getenv("AUTH_DATABASE_URL", database_url)' in server_cli
    assert '"127.0.0.1"' in server_cli
    assert '"7301"' in server_cli
    assert '"dev": "next dev --hostname 127.0.0.1 --port 7300"' in web_package
    assert (
        '"storybook": "storybook dev -p 7306 --host 127.0.0.1 --exact-port --no-open"'
        in web_package
    )
    assert '"dev": "next dev --hostname 127.0.0.1 --port 7303"' in legacy_package
    assert "--host 127.0.0.1 --port 7302" in jobs_api
    assert '"127.0.0.1:55672:5672"' in jobs_compose
    assert '"127.0.0.1:56379:6379"' in jobs_compose


def test_local_server_database_guard_accepts_only_registered_database() -> None:
    require_local_database_url(
        "postgresql://scholens_app:secret@127.0.0.1:55432/sanchezcloud"
    )


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://scholens_app:secret@localhost:55432/sanchezcloud",
        "postgresql://scholens_app:secret@127.0.0.1:5432/sanchezcloud",
        "postgresql://scholens_app:secret@db.example.com:5432/sanchezcloud",
        "postgresql://scholens_app:secret@127.0.0.1:55432/production",
        "postgresql://postgres:secret@127.0.0.1:55432/sanchezcloud",
        (
            "postgresql://scholens_app:secret@127.0.0.1:55432/sanchezcloud"
            "?host=db.example.com"
        ),
    ],
)
def test_local_server_database_guard_rejects_unknown_targets(database_url: str) -> None:
    with pytest.raises(ValueError, match="127.0.0.1:55432/sanchezcloud"):
        require_local_database_url(database_url)


def test_local_server_address_accepts_only_registered_loopback_port() -> None:
    require_local_server_address("127.0.0.1", 7301)

    with pytest.raises(ValueError, match="127.0.0.1:7301"):
        require_local_server_address("0.0.0.0", 7301)
    with pytest.raises(ValueError, match="127.0.0.1:7301"):
        require_local_server_address("127.0.0.1", 8000)
