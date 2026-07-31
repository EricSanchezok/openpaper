"""Provider-neutral extraction of verifiable external sources from tool output."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.shared.domain import JsonValue
from app.tooling.contracts import ExternalSourceCandidate

_URL_PATTERN = re.compile(r"https?://[^\s<>\"'\]\[(){}]+", re.IGNORECASE)
_DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
_URL_FIELDS = ("url", "link", "source_url", "sourceUrl", "href")
_TITLE_FIELDS = ("title", "name", "source", "site_name")
_EXCERPT_FIELDS = ("excerpt", "snippet", "content", "text", "description", "summary")
_MAX_SOURCE_URL_CHARS = 2_048
_MAX_SOURCE_EXCERPT_CHARS = 8_000
_MAX_SOURCES_PER_RESULT = 256


def normalize_external_url(value: str) -> str | None:
    candidate = value.strip().rstrip(".,;:!?")
    if len(candidate) > _MAX_SOURCE_URL_CHARS:
        return None
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    host = parsed.hostname.lower()
    port = parsed.port
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit(
        (parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, "")
    )


def extract_external_sources(
    *,
    arguments: Mapping[str, Any],
    payload: JsonValue,
    origin: Mapping[str, JsonValue] | None = None,
) -> tuple[ExternalSourceCandidate, ...]:
    """Extract URL-bound sources without knowing the provider or tool name."""
    serialized_arguments = json.dumps(arguments, ensure_ascii=False, default=str)
    serialized_payload = json.dumps(payload, ensure_ascii=False, default=str)
    searchable = f"{serialized_arguments}\n{serialized_payload}"
    candidates: list[ExternalSourceCandidate] = []
    seen: set[str] = set()

    def add(
        url: str,
        *,
        title: str | None = None,
        excerpt: str | None = None,
        provenance: str | None = None,
    ) -> None:
        normalized = normalize_external_url(url)
        if normalized is None or normalized in seen:
            return
        raw_without_fragment = url.split("#", 1)[0]
        if (
            raw_without_fragment not in searchable
            and normalized not in searchable
            and (provenance is None or provenance not in searchable)
        ):
            return
        clean_excerpt = excerpt.strip()[:_MAX_SOURCE_EXCERPT_CHARS] if excerpt else None
        if clean_excerpt and clean_excerpt not in searchable:
            clean_excerpt = None
        seen.add(normalized)
        candidates.append(
            ExternalSourceCandidate(
                url=normalized,
                title=title.strip()[:500] if title else None,
                excerpt=clean_excerpt,
                origin=dict(origin) if origin is not None else None,
            )
        )

    def visit(value: Any) -> None:
        if len(candidates) >= _MAX_SOURCES_PER_RESULT:
            return
        if isinstance(value, dict):
            url = next(
                (
                    value[field]
                    for field in _URL_FIELDS
                    if isinstance(value.get(field), str)
                ),
                None,
            )
            if isinstance(url, str):
                title = next(
                    (
                        value[field]
                        for field in _TITLE_FIELDS
                        if isinstance(value.get(field), str)
                    ),
                    None,
                )
                excerpt = next(
                    (
                        value[field]
                        for field in _EXCERPT_FIELDS
                        if isinstance(value.get(field), str)
                    ),
                    None,
                )
                add(url, title=title, excerpt=excerpt)
            for nested in value.values():
                visit(nested)
            return
        if isinstance(value, list):
            for nested in value:
                visit(nested)
            return
        if isinstance(value, str):
            for match in _URL_PATTERN.findall(value):
                add(match, excerpt=value)
            for doi in _DOI_PATTERN.findall(value):
                add(
                    f"https://doi.org/{doi}",
                    title=f"DOI {doi}",
                    excerpt=value,
                    provenance=doi,
                )

    visit(arguments)
    visit(payload)
    return tuple(candidates)
