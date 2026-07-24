from __future__ import annotations

from unittest.mock import patch

import pytest

from app.helpers.parser import _validate_public_http_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/paper.pdf",
        "https://user:password@example.com/paper.pdf",
    ],
)
def test_pdf_url_rejects_unsupported_or_credentialed_urls(url: str) -> None:
    with pytest.raises(ValueError):
        _validate_public_http_url(url)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "::1",
        "fc00::1",
        "fe80::1",
    ],
)
def test_pdf_url_rejects_non_public_dns_answers(address: str) -> None:
    family = 10 if ":" in address else 2
    with (
        patch(
            "app.helpers.parser.socket.getaddrinfo",
            return_value=[(family, 1, 6, "", (address, 443))],
        ),
        pytest.raises(ValueError, match="public"),
    ):
        _validate_public_http_url("https://example.com/paper.pdf")


def test_pdf_url_accepts_only_when_all_dns_answers_are_public() -> None:
    answers = [
        (2, 1, 6, "", ("93.184.216.34", 443)),
        (10, 1, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 443, 0, 0)),
    ]
    with patch("app.helpers.parser.socket.getaddrinfo", return_value=answers):
        _validate_public_http_url("https://example.com/paper.pdf")
