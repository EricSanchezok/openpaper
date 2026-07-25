"""Safe formatting for connection strings and external-service failures."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "key",
    "password",
    "secret",
    "signature",
    "token",
}


def redact_url(value: str) -> str:
    """Redact credentials and sensitive query values while preserving topology."""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "<redacted-url>"

    if not parsed.scheme:
        return "<redacted-url>"

    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    credentials = "***:***@" if parsed.username is not None else ""
    netloc = f"{credentials}{hostname}{port}"
    query = urlencode(
        [
            (key, "***" if key.lower() in _SENSITIVE_QUERY_KEYS else item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        ]
    )
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, ""))
