"""Provider-neutral extraction of verifiable external sources from tool output."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from app.shared.domain import JsonValue
from app.tooling.contracts import ExternalSourceCandidate, ExternalSourceProvenance

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
_SourceOrigin = Literal["arguments", "payload"]


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
) -> tuple[ExternalSourceCandidate, ...]:
    """Extract URL-bound sources without knowing the provider or tool name."""
    candidates: dict[tuple[str, str], tuple[ExternalSourceCandidate, int]] = {}

    def first_payload_excerpt(
        value: Any,
        path: tuple[str | int, ...] = (),
    ) -> tuple[tuple[str | int, ...], str] | None:
        if isinstance(value, dict):
            for field in _EXCERPT_FIELDS:
                candidate = value.get(field)
                if isinstance(candidate, str) and candidate.strip():
                    return (*path, field), candidate
            for key, nested in value.items():
                excerpt = first_payload_excerpt(nested, (*path, key))
                if excerpt is not None:
                    return excerpt
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                excerpt = first_payload_excerpt(nested, (*path, index))
                if excerpt is not None:
                    return excerpt
        elif isinstance(value, str) and value.strip():
            return path, value
        return None

    fallback_payload_excerpt = first_payload_excerpt(payload)

    def bounded_slice(value: str) -> tuple[str, int, int] | None:
        stripped = value.strip()
        if not stripped:
            return None
        start = value.find(stripped)
        excerpt = stripped[:_MAX_SOURCE_EXCERPT_CHARS]
        return excerpt, start, start + len(excerpt)

    def normalized_url_slice(value: str) -> tuple[str, int, int] | None:
        stripped = value.strip().rstrip(".,;:!?")
        normalized = normalize_external_url(stripped)
        if normalized is None:
            return None
        start = value.find(stripped)
        return normalized, start, start + len(stripped)

    def add(
        url: str,
        *,
        url_origin: _SourceOrigin,
        url_path: tuple[str | int, ...],
        url_start: int,
        url_end: int,
        title: str | None = None,
        excerpt_value: str | None = None,
        excerpt_path: tuple[str | int, ...] | None = None,
        quality: int = 0,
    ) -> None:
        normalized = normalize_external_url(url)
        if normalized is None:
            return
        excerpt_slice = bounded_slice(excerpt_value) if excerpt_value else None
        clean_excerpt = excerpt_slice[0] if excerpt_slice is not None else None
        candidate = ExternalSourceCandidate(
            url=normalized,
            title=title.strip()[:500] if title else None,
            excerpt=clean_excerpt,
            provenance=ExternalSourceProvenance(
                url_origin=url_origin,
                url_path=url_path,
                url_start=url_start,
                url_end=url_end,
                excerpt_path=excerpt_path if excerpt_slice is not None else None,
                excerpt_start=excerpt_slice[1] if excerpt_slice is not None else None,
                excerpt_end=excerpt_slice[2] if excerpt_slice is not None else None,
            ),
        )
        candidate_key = (normalized, " ".join((clean_excerpt or "").split()))
        existing_entry = candidates.get(candidate_key)
        existing = existing_entry[0] if existing_entry is not None else None
        existing_quality = existing_entry[1] if existing_entry is not None else -1
        if existing is None:
            candidates[candidate_key] = (candidate, quality)
        elif (
            quality > existing_quality
            or (existing.title is None and candidate.title is not None)
        ):
            candidates[candidate_key] = (
                ExternalSourceCandidate(
                    url=normalized,
                    title=candidate.title or existing.title,
                    excerpt=(
                        candidate.excerpt
                        if quality > existing_quality
                        else existing.excerpt
                    ),
                    provenance=candidate.provenance or existing.provenance,
                ),
                max(quality, existing_quality),
            )

    def visit(
        value: Any,
        *,
        origin_name: _SourceOrigin,
        path: tuple[str | int, ...] = (),
    ) -> None:
        if len(candidates) >= _MAX_SOURCES_PER_RESULT:
            return
        if isinstance(value, dict):
            url_entry = next(
                (
                    (field, value[field])
                    for field in _URL_FIELDS
                    if isinstance(value.get(field), str)
                ),
                None,
            )
            if url_entry is not None:
                url_field, url = url_entry
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
                        (field, value[field])
                        for field in _EXCERPT_FIELDS
                        if isinstance(value.get(field), str)
                    ),
                    None,
                )
                url_slice = normalized_url_slice(url)
                if url_slice is not None:
                    normalized, url_start, url_end = url_slice
                    structured_excerpt: tuple[tuple[str | int, ...], str] | None
                    if origin_name == "payload" and excerpt is not None:
                        excerpt_field, excerpt_value = excerpt
                        structured_excerpt = ((*path, excerpt_field), str(excerpt_value))
                    else:
                        structured_excerpt = fallback_payload_excerpt
                    add(
                        normalized,
                        url_origin=origin_name,
                        url_path=(*path, url_field),
                        url_start=url_start,
                        url_end=url_end,
                        title=title,
                        excerpt_value=(
                            structured_excerpt[1]
                            if structured_excerpt is not None
                            else None
                        ),
                        excerpt_path=(
                            structured_excerpt[0]
                            if structured_excerpt is not None
                            else None
                        ),
                        quality=(
                            _SOURCE_QUALITY_STRUCTURED_RESULT
                            if origin_name == "payload" and excerpt is not None
                            else _SOURCE_QUALITY_ARGUMENT_BOUND
                        ),
                    )
            for key, nested in value.items():
                if key in _URL_FIELDS and isinstance(nested, str):
                    continue
                visit(nested, origin_name=origin_name, path=(*path, key))
            return
        if isinstance(value, list):
            for index, nested in enumerate(value):
                visit(nested, origin_name=origin_name, path=(*path, index))
            return
        if isinstance(value, str):
            leaf_excerpt: tuple[tuple[str | int, ...], str] | None = (
                (path, value) if origin_name == "payload" else fallback_payload_excerpt
            )
            for match in _URL_PATTERN.finditer(value):
                raw_url = match.group(0).rstrip(".,;:!?")
                add(
                    raw_url,
                    url_origin=origin_name,
                    url_path=path,
                    url_start=match.start(),
                    url_end=match.start() + len(raw_url),
                    excerpt_value=(
                        leaf_excerpt[1] if leaf_excerpt is not None else None
                    ),
                    excerpt_path=(
                        leaf_excerpt[0] if leaf_excerpt is not None else None
                    ),
                    quality=(
                        _SOURCE_QUALITY_RESULT_TEXT
                        if origin_name == "payload"
                        else _SOURCE_QUALITY_ARGUMENT_BOUND
                    ),
                )
            for match in _DOI_PATTERN.finditer(value):
                doi = match.group(0)
                add(
                    f"https://doi.org/{doi}",
                    url_origin=origin_name,
                    url_path=path,
                    url_start=match.start(),
                    url_end=match.end(),
                    title=f"DOI {doi}",
                    excerpt_value=(
                        leaf_excerpt[1] if leaf_excerpt is not None else None
                    ),
                    excerpt_path=(
                        leaf_excerpt[0] if leaf_excerpt is not None else None
                    ),
                    quality=(
                        _SOURCE_QUALITY_RESULT_TEXT
                        if origin_name == "payload"
                        else _SOURCE_QUALITY_ARGUMENT_BOUND
                    ),
                )

    visit(arguments, origin_name="arguments")
    visit(payload, origin_name="payload")
    return tuple(candidate for candidate, _quality in candidates.values())


def verify_external_source(
    candidate: ExternalSourceCandidate,
    *,
    arguments: Mapping[str, Any],
    payload: JsonValue,
) -> bool:
    """Verify a candidate against the immutable raw tool observation."""
    provenance = candidate.provenance
    if provenance is None:
        return False

    def value_at(root: Any, path: tuple[str | int, ...]) -> Any:
        current = root
        for segment in path:
            if isinstance(segment, str) and isinstance(current, Mapping):
                current = current.get(segment)
            elif isinstance(segment, int) and isinstance(current, list):
                if segment < 0 or segment >= len(current):
                    return None
                current = current[segment]
            else:
                return None
        return current

    url_root = arguments if provenance.url_origin == "arguments" else payload
    url_value = value_at(url_root, provenance.url_path)
    if not isinstance(url_value, str):
        return False
    if not (0 <= provenance.url_start < provenance.url_end <= len(url_value)):
        return False
    raw_identity = url_value[provenance.url_start : provenance.url_end]
    if _DOI_PATTERN.fullmatch(raw_identity):
        verified_url = normalize_external_url(f"https://doi.org/{raw_identity}")
    else:
        verified_url = normalize_external_url(raw_identity)
    if verified_url != normalize_external_url(candidate.url):
        return False

    if candidate.excerpt is None:
        return provenance.excerpt_path is None
    if (
        provenance.excerpt_path is None
        or provenance.excerpt_start is None
        or provenance.excerpt_end is None
    ):
        return False
    excerpt_value = value_at(payload, provenance.excerpt_path)
    if not isinstance(excerpt_value, str):
        return False
    if not (
        0
        <= provenance.excerpt_start
        < provenance.excerpt_end
        <= len(excerpt_value)
    ):
        return False
    return (
        excerpt_value[provenance.excerpt_start : provenance.excerpt_end]
        == candidate.excerpt
    )
