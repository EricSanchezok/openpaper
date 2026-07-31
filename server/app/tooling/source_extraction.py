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
_SOURCE_QUALITY_ARGUMENT_BOUND = 1
_SOURCE_QUALITY_RESULT_TEXT = 2
_SOURCE_QUALITY_STRUCTURED_RESULT = 3


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
    candidates: dict[str, tuple[ExternalSourceCandidate, int]] = {}

    def first_payload_excerpt(value: Any) -> str | None:
        if isinstance(value, dict):
            for field in _EXCERPT_FIELDS:
                candidate = value.get(field)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate
            for nested in value.values():
                excerpt = first_payload_excerpt(nested)
                if excerpt is not None:
                    return excerpt
        elif isinstance(value, list):
            for nested in value:
                excerpt = first_payload_excerpt(nested)
                if excerpt is not None:
                    return excerpt
        elif isinstance(value, str) and value.strip():
            return value
        return None

    fallback_payload_excerpt = first_payload_excerpt(payload)

    def add(
        url: str,
        *,
        title: str | None = None,
        excerpt: str | None = None,
        provenance: str | None = None,
        quality: int = 0,
    ) -> None:
        normalized = normalize_external_url(url)
        if normalized is None:
            return
        raw_without_fragment = url.split("#", 1)[0]
        if (
            raw_without_fragment not in searchable
            and normalized not in searchable
            and (provenance is None or provenance not in searchable)
        ):
            return
        clean_excerpt = excerpt.strip()[:_MAX_SOURCE_EXCERPT_CHARS] if excerpt else None
        if clean_excerpt and clean_excerpt not in serialized_payload:
            clean_excerpt = None
        candidate = ExternalSourceCandidate(
            url=normalized,
            title=title.strip()[:500] if title else None,
            excerpt=clean_excerpt,
            origin=dict(origin) if origin is not None else None,
        )
        existing_entry = candidates.get(normalized)
        existing = existing_entry[0] if existing_entry is not None else None
        existing_quality = existing_entry[1] if existing_entry is not None else -1
        if existing is None:
            candidates[normalized] = (candidate, quality)
        elif (
            quality > existing_quality
            or (existing.title is None and candidate.title is not None)
        ):
            candidates[normalized] = (
                ExternalSourceCandidate(
                    url=normalized,
                    title=candidate.title or existing.title,
                    excerpt=(
                        candidate.excerpt
                        if quality > existing_quality
                        else existing.excerpt
                    ),
                    origin=candidate.origin or existing.origin,
                ),
                max(quality, existing_quality),
            )

    def visit(value: Any, *, payload_value: bool) -> None:
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
                add(
                    url,
                    title=title,
                    excerpt=excerpt if payload_value else fallback_payload_excerpt,
                    quality=(
                        _SOURCE_QUALITY_STRUCTURED_RESULT
                        if payload_value and excerpt
                        else _SOURCE_QUALITY_ARGUMENT_BOUND
                    ),
                )
            for nested in value.values():
                visit(nested, payload_value=payload_value)
            return
        if isinstance(value, list):
            for nested in value:
                visit(nested, payload_value=payload_value)
            return
        if isinstance(value, str):
            for match in _URL_PATTERN.findall(value):
                add(
                    match,
                    excerpt=value if payload_value else fallback_payload_excerpt,
                    quality=(
                        _SOURCE_QUALITY_RESULT_TEXT
                        if payload_value
                        else _SOURCE_QUALITY_ARGUMENT_BOUND
                    ),
                )
            for doi in _DOI_PATTERN.findall(value):
                add(
                    f"https://doi.org/{doi}",
                    title=f"DOI {doi}",
                    excerpt=value if payload_value else fallback_payload_excerpt,
                    provenance=doi,
                    quality=(
                        _SOURCE_QUALITY_RESULT_TEXT
                        if payload_value
                        else _SOURCE_QUALITY_ARGUMENT_BOUND
                    ),
                )

    visit(arguments, payload_value=False)
    visit(payload, payload_value=True)
    return tuple(candidate for candidate, _quality in candidates.values())
