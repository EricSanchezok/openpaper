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
    normalize_external_url,
    verify_external_source,
)
from pydantic import TypeAdapter

ANSWER_PACKET_TOKEN_BUDGET = 450_000
_MATERIAL_TOKEN_BUDGET = 280_000
_SOURCE_TOKEN_BUDGET = 100_000
_CONTEXT_TOKEN_BUDGET = 15_000
_ACTION_TOKEN_BUDGET = 15_000
_DOCUMENT_CHUNK_CHARS = 6_000
_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _normalized_external_reference(value: str) -> str:
    """Ignore provider-added result ordinals when identifying one source excerpt."""
    return re.sub(
        r"^(?:#{1,6}\s*)?(?:\d+[.)]\s*)",
        "",
        _normalized_text(value),
    )


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


def _bound_json_value(value: JsonValue, max_tokens: int) -> tuple[JsonValue, bool]:
    serialized = json.dumps(value, ensure_ascii=False, default=str)
    if estimate_tokens(serialized) <= max_tokens:
        return value, False

    content_budget = max(1, max_tokens)
    while content_budget > 1:
        bounded: JsonValue = {
            "truncated": True,
            "content": truncate_to_token_budget(serialized, content_budget),
        }
        if estimate_tokens(json.dumps(bounded, ensure_ascii=False)) <= max_tokens:
            return bounded, True
        content_budget = max(1, content_budget * 3 // 4)
    return {"truncated": True}, True


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
            f"external:{normalized_url}:{_normalized_external_reference(excerpt)}".encode()
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
            verified_candidates: list[ToolSourceCandidate] = []
            for candidate in observation.sources:
                if isinstance(candidate, DocumentSourceCandidate):
                    verified_candidates.append(candidate)
                    continue
                if not verify_external_source(
                    candidate,
                    arguments=observation.args,
                    payload=observation.payload,
                ):
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
            if isinstance(candidate, ExternalSourceCandidate):
                registry.reject()
                continue
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
            truncated_materials=0,
            truncated_sources=0,
            truncated_actions=0,
            context_truncated=False,
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
        bounded_context_value, context_truncated = _bound_json_value(
            packet.context,
            _CONTEXT_TOKEN_BUDGET,
        )
        bounded_context = (
            bounded_context_value
            if isinstance(bounded_context_value, dict)
            else {"truncated": True, "content": bounded_context_value}
        )
        bounded_materials: list[AnswerMaterial] = []
        per_material = max(1, _MATERIAL_TOKEN_BUDGET // max(1, len(packet.materials)))
        for material in packet.materials:
            content, truncated = _bound_json_value(material.content, per_material)
            if truncated:
                if material.id.startswith("o"):
                    truncated_observations.add(material.id.split("-", 1)[0])
            bounded_materials.append(material.model_copy(update={"content": content}))

        bounded_sources: list[AnswerSource] = []
        truncated_sources = 0
        per_source = max(1, _SOURCE_TOKEN_BUDGET // max(1, len(packet.sources)))
        for source in packet.sources:
            reference = source.reference
            if reference and estimate_tokens(reference) > per_source:
                source = source.model_copy(
                    update={"reference": _exact_prefix(reference, per_source)}
                )
                truncated_sources += 1
            bounded_sources.append(source)

        bounded_actions: list[dict[str, JsonValue]] = []
        truncated_actions = 0
        per_action = max(1, _ACTION_TOKEN_BUDGET // max(1, len(packet.actions)))
        for action in packet.actions:
            bounded_action, truncated = _bound_json_value(action, per_action)
            if truncated:
                truncated_actions += 1
            bounded_actions.append(
                bounded_action
                if isinstance(bounded_action, dict)
                else {"truncated": True, "content": bounded_action}
            )

        coverage = packet.coverage.model_copy(
            update={
                "truncated_observations": len(truncated_observations),
                "truncated_sources": truncated_sources,
                "truncated_actions": truncated_actions,
                "context_truncated": context_truncated,
            }
        )
        bounded_packet = packet.model_copy(
            update={
                "context": bounded_context,
                "materials": bounded_materials,
                "actions": bounded_actions,
                "sources": bounded_sources,
                "coverage": coverage,
            }
        )
        if (
            estimate_tokens(bounded_packet.model_dump_json())
            <= ANSWER_PACKET_TOKEN_BUDGET
        ):
            return bounded_packet
        return AnswerPacketBuilder._fit_material_metadata(
            bounded_packet,
            truncated_observation_ids=truncated_observations,
        )

    @staticmethod
    def _fit_material_metadata(
        packet: AnswerPacket,
        *,
        truncated_observation_ids: set[str],
    ) -> AnswerPacket:
        """Fairly omit whole materials when their JSON metadata alone is too large."""

        def sample(count: int) -> list[AnswerMaterial]:
            if count >= len(packet.materials):
                return packet.materials
            if count <= 0:
                return []
            total = len(packet.materials)
            return [packet.materials[index * total // count] for index in range(count)]

        def candidate(count: int) -> AnswerPacket:
            materials = sample(count)
            used_source_keys = {
                key for material in materials for key in material.source_keys
            }
            sources = [
                source for source in packet.sources if source.key in used_source_keys
            ]
            kept_ids = {material.id for material in materials}
            removed_observations = {
                material.id.split("-", 1)[0]
                for material in packet.materials
                if material.id.startswith("o") and material.id not in kept_ids
            }
            coverage = packet.coverage.model_copy(
                update={
                    "truncated_observations": (
                        len(truncated_observation_ids | removed_observations)
                    ),
                    "truncated_materials": len(packet.materials) - len(materials),
                    "truncated_sources": (
                        packet.coverage.truncated_sources
                        + len(packet.sources)
                        - len(sources)
                    ),
                }
            )
            return packet.model_copy(
                update={
                    "materials": materials,
                    "sources": sources,
                    "coverage": coverage,
                }
            )

        low = 0
        high = len(packet.materials)
        best = candidate(0)
        while low <= high:
            middle = (low + high) // 2
            current = candidate(middle)
            if estimate_tokens(current.model_dump_json()) <= ANSWER_PACKET_TOKEN_BUDGET:
                best = current
                low = middle + 1
            else:
                high = middle - 1
        return best
