"""Build bounded final-answer material and enforce server-owned citations."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from uuid import UUID

from app.modules.conversations.application.contracts.answer_packet import (
    AnswerCoverage,
    AnswerMaterial,
    AnswerPacket,
    AnswerSource,
    DocumentAnswerSource,
    ExternalAnswerSource,
    MessageReference,
    MessageReferences,
)
from app.modules.conversations.application.contracts.messages import ToolRunState
from app.shared.application.context_budget import (
    estimate_tokens,
    truncate_to_token_budget,
)
from app.shared.domain import JsonValue
from app.tooling.contracts import (
    DocumentSourceCandidate,
    ExternalSourceCandidate,
    ToolSourceCandidate,
)
from app.tooling.source_extraction import (
    extract_external_sources,
    normalize_external_url,
)
from pydantic import TypeAdapter

ANSWER_PACKET_TOKEN_BUDGET = 450_000
_MATERIAL_TOKEN_BUDGET = 300_000
_SOURCE_TOKEN_BUDGET = 120_000
_DOCUMENT_CHUNK_CHARS = 6_000
_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
_CITATION_PATTERN = re.compile(r"\[\^(\d+(?:\s*,\s*\^?\d+)*)\]")
_INCOMPLETE_CITATION_PATTERN = re.compile(r"\[\^\d+(?:\s*,\s*\^?\d+)*$", re.DOTALL)
_OUTPUT_URL_PATTERN = re.compile(r"https?://[^\s<>\]\[(){}]+", re.IGNORECASE)
_OUTPUT_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_PARTIAL_UUID_PATTERN = re.compile(r"[0-9a-f-]{1,36}$", re.IGNORECASE)


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _document_chunks(value: str) -> list[str]:
    text = value.strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + _DOCUMENT_CHUNK_CHARS)
        if end < len(text):
            boundary = text.rfind("\n", start, end)
            if boundary > start:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = max(end, start + 1)
    return chunks


def _exact_prefix(value: str, max_tokens: int) -> str:
    encoded = value.encode("utf-8")
    return encoded[: max_tokens * 3].decode("utf-8", errors="ignore").strip()


class SourceRegistry:
    """Admit, deduplicate, and number sources without model-generated identity."""

    def __init__(
        self,
        *,
        document_source_texts: Mapping[UUID, Sequence[str]] | None = None,
    ) -> None:
        self._sources: list[AnswerSource] = []
        self._dedupe: dict[str, int] = {}
        self._document_source_texts = (
            {
                document_id: tuple(
                    _normalized_text(text) for text in texts if text.strip()
                )
                for document_id, texts in document_source_texts.items()
            }
            if document_source_texts is not None
            else None
        )
        self.rejected_sources = 0

    @property
    def sources(self) -> list[AnswerSource]:
        return list(self._sources)

    def reject(self) -> None:
        self.rejected_sources += 1

    def add(self, candidate: ToolSourceCandidate) -> list[int]:
        if isinstance(candidate, DocumentSourceCandidate):
            return self._add_document(candidate)
        return self._add_external(candidate)

    def add_all(self, candidates: Iterable[ToolSourceCandidate]) -> list[int]:
        keys: list[int] = []
        for candidate in candidates:
            keys.extend(self.add(candidate))
        return list(dict.fromkeys(keys))

    def _add_document(self, candidate: DocumentSourceCandidate) -> list[int]:
        verified_texts = (
            self._document_source_texts.get(candidate.document_id)
            if self._document_source_texts is not None
            else None
        )
        if self._document_source_texts is not None and verified_texts is None:
            self.rejected_sources += 1
            return []
        chunks = _document_chunks(candidate.excerpt)
        if not chunks:
            self.rejected_sources += 1
            return []
        keys: list[int] = []
        for chunk in chunks:
            normalized = _normalized_text(chunk)
            if verified_texts is not None and not any(
                normalized in source_text for source_text in verified_texts
            ):
                self.rejected_sources += 1
                continue
            fingerprint = hashlib.sha256(
                f"document:{candidate.document_id}:{normalized}".encode()
            ).hexdigest()
            existing = self._dedupe.get(fingerprint)
            if existing is not None:
                keys.append(existing)
                continue
            key = len(self._sources) + 1
            source = DocumentAnswerSource(
                key=key,
                document_id=candidate.document_id,
                title=candidate.title,
                authors=list(candidate.authors),
                reference=chunk,
                locator=candidate.locator,
            )
            self._dedupe[fingerprint] = key
            self._sources.append(source)
            keys.append(key)
        return keys

    def _add_external(self, candidate: ExternalSourceCandidate) -> list[int]:
        normalized_url = normalize_external_url(candidate.url)
        excerpt = candidate.excerpt.strip() if candidate.excerpt else ""
        if normalized_url is None or not excerpt:
            self.rejected_sources += 1
            return []
        fingerprint = hashlib.sha256(
            f"external:{normalized_url}:{_normalized_text(excerpt)}".encode()
        ).hexdigest()
        existing = self._dedupe.get(fingerprint)
        if existing is not None:
            return [existing]
        key = len(self._sources) + 1
        source = ExternalAnswerSource.model_validate(
            {
                "key": key,
                "url": normalized_url,
                "title": candidate.title,
                "reference": excerpt,
            }
        )
        self._dedupe[fingerprint] = key
        self._sources.append(source)
        return [key]


class AnswerPacketBuilder:
    def build(
        self,
        *,
        context: Mapping[str, JsonValue],
        tool_state: ToolRunState,
        direct_sources: Sequence[ToolSourceCandidate] = (),
        user_materials: Sequence[str] = (),
        document_source_texts: Mapping[UUID, Sequence[str]] | None = None,
    ) -> AnswerPacket:
        registry = SourceRegistry(
            document_source_texts=document_source_texts,
        )
        materials: list[AnswerMaterial] = []

        for observation in tool_state.observations:
            extracted_external = extract_external_sources(
                arguments=observation.args,
                payload=observation.payload,
            )
            extracted_by_url = {source.url: source for source in extracted_external}
            verified_candidates: list[ToolSourceCandidate] = []
            for candidate in observation.sources:
                if isinstance(candidate, DocumentSourceCandidate):
                    verified_candidates.append(candidate)
                    continue
                normalized_url = normalize_external_url(candidate.url)
                extracted = (
                    extracted_by_url.get(normalized_url)
                    if normalized_url is not None
                    else None
                )
                excerpt_matches = candidate.excerpt is None or (
                    extracted is not None
                    and extracted.excerpt is not None
                    and _normalized_text(candidate.excerpt)
                    in _normalized_text(extracted.excerpt)
                )
                if extracted is None or not excerpt_matches:
                    registry.reject()
                    continue
                verified_candidates.append(candidate)
            source_keys = registry.add_all(verified_candidates)
            if observation.action_only:
                continue
            contents = observation.materials or [observation.payload]
            for material_index, content in enumerate(contents):
                materials.append(
                    AnswerMaterial(
                        id=f"o{observation.result_index}-{material_index}",
                        content=_JSON_VALUE.validate_python(content),
                        source_keys=source_keys,
                    )
                )

        for source_index, candidate in enumerate(direct_sources):
            keys = registry.add(candidate)
            if not keys:
                continue
            materials.append(
                AnswerMaterial(
                    id=f"direct-{source_index}",
                    content={
                        "kind": "direct_source",
                        "title": candidate.title,
                        "locator": (
                            candidate.locator
                            if isinstance(candidate, DocumentSourceCandidate)
                            else None
                        ),
                    },
                    source_keys=keys,
                )
            )

        for material_index, content in enumerate(user_materials):
            materials.append(
                AnswerMaterial(
                    id=f"user-{material_index}",
                    content=content,
                )
            )

        coverage = AnswerCoverage(
            observations_total=len(tool_state.observations)
            + tool_state.failed_observations,
            observations_processed=len(tool_state.observations),
            truncated_observations=0,
            rejected_sources=registry.rejected_sources,
            failed_observations=tool_state.failed_observations,
        )
        packet = AnswerPacket(
            context=dict(context),
            materials=materials,
            actions=tool_state.action_results,
            sources=registry.sources,
            coverage=coverage,
        )
        if estimate_tokens(packet.model_dump_json()) <= ANSWER_PACKET_TOKEN_BUDGET:
            return packet
        return self._bound(packet)

    @staticmethod
    def _bound(packet: AnswerPacket) -> AnswerPacket:
        truncated_observations: set[str] = set()
        bounded_materials: list[AnswerMaterial] = []
        per_material = max(1, _MATERIAL_TOKEN_BUDGET // max(1, len(packet.materials)))
        for material in packet.materials:
            serialized = json.dumps(material.content, ensure_ascii=False, default=str)
            bounded = truncate_to_token_budget(serialized, per_material)
            if bounded != serialized:
                if material.id.startswith("o"):
                    truncated_observations.add(material.id.split("-", 1)[0])
                content: JsonValue = bounded
            else:
                content = material.content
            bounded_materials.append(material.model_copy(update={"content": content}))

        bounded_sources: list[AnswerSource] = []
        per_source = max(1, _SOURCE_TOKEN_BUDGET // max(1, len(packet.sources)))
        for source in packet.sources:
            reference = source.reference
            if reference and estimate_tokens(reference) > per_source:
                source = source.model_copy(
                    update={"reference": _exact_prefix(reference, per_source)}
                )
            bounded_sources.append(source)

        coverage = packet.coverage.model_copy(
            update={"truncated_observations": len(truncated_observations)}
        )
        return packet.model_copy(
            update={
                "materials": bounded_materials,
                "sources": bounded_sources,
                "coverage": coverage,
            }
        )


class CitationMarkerFilter:
    """Filter streamed citation markers against a server-owned source registry."""

    def __init__(self, sources: Sequence[AnswerSource]) -> None:
        self._sources = {source.key: source for source in sources}
        self._buffer = ""
        self.used_keys: set[int] = set()

    def feed(self, value: str) -> str:
        self._buffer += value
        last_open = self._buffer.rfind("[")
        hold_from = len(self._buffer)
        if last_open >= 0 and "]" not in self._buffer[last_open:]:
            hold_from = min(hold_from, last_open)
        token_start = (
            max(
                self._buffer.rfind(separator)
                for separator in (" ", "\n", "\t", "(", "<")
            )
            + 1
        )
        tail = self._buffer[token_start:]
        if tail and tail[-1] not in " \n\t.,;:!?)]}>\"'":
            hold_from = min(hold_from, token_start)
        if (
            "https://".startswith(tail.lower())
            or "http://".startswith(tail.lower())
            or tail.lower().startswith(("http://", "https://"))
            or ("-" in tail and _PARTIAL_UUID_PATTERN.fullmatch(tail) is not None)
        ):
            hold_from = min(hold_from, token_start)
        ready = self._buffer[:hold_from]
        self._buffer = self._buffer[hold_from:]
        return self._filter(ready)

    def finish(self) -> str:
        remaining = _INCOMPLETE_CITATION_PATTERN.sub("", self._filter(self._buffer))
        self._buffer = ""
        return remaining

    def references(self) -> MessageReferences | None:
        citations: list[MessageReference] = [
            self._sources[key] for key in sorted(self.used_keys) if key in self._sources
        ]
        return MessageReferences(citations=citations) if citations else None

    def _filter(self, value: str) -> str:
        def replace(match: re.Match[str]) -> str:
            requested = [
                int(item.strip().removeprefix("^"))
                for item in match.group(1).split(",")
            ]
            valid = [key for key in requested if key in self._sources]
            self.used_keys.update(valid)
            if not valid:
                return ""
            return "[^" + ", ^".join(str(key) for key in valid) + "]"

        filtered = _CITATION_PATTERN.sub(replace, value)
        filtered = _OUTPUT_URL_PATTERN.sub("", filtered)
        return _OUTPUT_UUID_PATTERN.sub("", filtered)
