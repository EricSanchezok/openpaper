from dataclasses import replace
from uuid import uuid4

from app.llm.answer_packet import AnswerPacketBuilder, SourceRegistry
from app.llm.grounded_answer import GroundedAnswerStreamParser
from app.modules.conversations.application.contracts.answer_packet import (
    ExternalAnswerSource,
)
from app.modules.papers.application.citation_references import (
    materialize_summary_references,
)
from app.modules.papers.application.contracts.extraction import ResponseCitation
from app.modules.conversations.application.contracts.messages import ToolRunState
from app.modules.papers.application.contracts.extraction import ToolCall
from app.tooling import (
    DocumentSourceCandidate,
    ExternalSourceCandidate,
    ToolOutcome,
)
from app.tooling.source_extraction import (
    extract_external_sources,
    verify_external_source,
)


def test_answer_packet_keeps_general_materials_actions_and_typed_sources() -> None:
    document_id = uuid4()
    state = ToolRunState()
    state.add_tool_outcome(
        ToolCall(id="read", name="get_paper_content_range", args={}),
        ToolOutcome(
            payload={"method": "measured result", "score": 0.91},
            sources=(
                DocumentSourceCandidate(
                    document_id=document_id,
                    title="A paper",
                    authors=("Ada",),
                    excerpt="The measured result was 0.91.",
                    locator={"start_line": 12},
                ),
            ),
        ),
    )
    state.add_tool_outcome(
        ToolCall(id="create", name="create_project", args={}),
        ToolOutcome(
            payload={"project_id": "project-1"},
            action={"kind": "project_created", "project_id": "project-1"},
        ),
    )

    packet = AnswerPacketBuilder().build(
        context={"scope": "global"},
        tool_state=state,
        document_source_texts={document_id: ("The measured result was 0.91.",)},
    )

    assert [material.content for material in packet.materials] == [
        {"method": "measured result", "score": 0.91}
    ]
    assert packet.actions == [{"kind": "project_created", "project_id": "project-1"}]
    assert packet.sources[0].kind == "document"
    assert packet.sources[0].key == 1
    assert packet.materials[0].source_keys == [1]


def test_document_source_is_rejected_after_access_is_lost() -> None:
    state = ToolRunState()
    state.add_tool_outcome(
        ToolCall(id="read", name="get_paper_content", args={}),
        ToolOutcome(
            payload={"content": "private"},
            sources=(
                DocumentSourceCandidate(
                    document_id=uuid4(),
                    excerpt="private",
                ),
            ),
        ),
    )

    packet = AnswerPacketBuilder().build(
        context={},
        tool_state=state,
        document_source_texts={},
    )

    assert packet.sources == []
    assert packet.materials[0].source_keys == []
    assert packet.coverage.rejected_sources == 1


def test_document_source_excerpt_must_belong_to_verified_document_text() -> None:
    document_id = uuid4()
    state = ToolRunState()
    state.add_tool_outcome(
        ToolCall(id="read", name="get_paper_content", args={}),
        ToolOutcome(
            payload={"content": "A forged excerpt"},
            sources=(
                DocumentSourceCandidate(
                    document_id=document_id,
                    excerpt="A forged excerpt",
                ),
            ),
        ),
    )

    packet = AnswerPacketBuilder().build(
        context={},
        tool_state=state,
        document_source_texts={document_id: ("The actual paper text",)},
    )

    assert packet.sources == []
    assert packet.coverage.rejected_sources == 1


def test_connector_source_extraction_requires_result_provenance() -> None:
    sources = extract_external_sources(
        arguments={"query": "test"},
        payload={
            "results": [
                {
                    "title": "Result",
                    "url": "https://example.org/paper#section",
                    "snippet": "A result-backed excerpt",
                }
            ],
            "unrelated": "doi:10.1000/test.1",
        },
    )

    assert {source.url for source in sources} == {
        "https://example.org/paper",
        "https://doi.org/10.1000/test.1",
    }
    assert sources[0].excerpt == "A result-backed excerpt"
    assert sources[0].provenance is not None


def test_external_url_argument_is_bound_to_result_excerpt_not_to_itself() -> None:
    sources = extract_external_sources(
        arguments={"url": "https://example.org/paper"},
        payload={"content": "The returned page supports the result."},
    )

    assert len(sources) == 1
    assert sources[0].url == "https://example.org/paper"
    assert sources[0].excerpt == "The returned page supports the result."


def test_source_registry_deduplicates_provider_result_ordinals() -> None:
    registry = SourceRegistry()

    first = registry.add(
        ExternalSourceCandidate(
            url="https://example.org/paper",
            excerpt="### 2. Paper title\n- Same verified source excerpt.",
        )
    )
    second = registry.add(
        ExternalSourceCandidate(
            url="https://example.org/paper",
            excerpt="### 7. Paper title\n- Same verified source excerpt.",
        )
    )

    assert first == second == [1]
    assert len(registry.sources) == 1


def test_resource_url_owns_returned_content_instead_of_embedded_links() -> None:
    sources = extract_external_sources(
        arguments={"url": "https://example.org/paper"},
        payload={
            "content": (
                "# Paper\n\nThe paper reports a result and links to "
                "https://github.com/example/code for its implementation."
            )
        },
    )

    assert {source.url for source in sources} == {"https://example.org/paper"}
    assert any("reports a result" in (source.excerpt or "") for source in sources)


def test_long_resource_content_is_split_into_verifiable_source_excerpts() -> None:
    content = "A" * 9_000 + "\n\n" + "B" * 2_000
    arguments = {"url": "https://example.org/paper"}
    payload = {"content": content}

    sources = extract_external_sources(arguments=arguments, payload=payload)

    assert len(sources) >= 2
    assert {source.url for source in sources} == {"https://example.org/paper"}
    assert all(
        verify_external_source(source, arguments=arguments, payload=payload)
        for source in sources
    )


def test_external_source_preserves_multiline_quotes_and_unicode() -> None:
    excerpt = '第一行说“压缩”。\nSecond line contains "quotes" and an emoji 🧠.'
    arguments = {"url": "https://example.org/paper"}
    payload = {"content": excerpt}
    sources = extract_external_sources(arguments=arguments, payload=payload)

    state = ToolRunState()
    state.add_tool_outcome(
        ToolCall(id="remote", name="extract", args=arguments),
        ToolOutcome(payload=payload, sources=sources),
    )
    packet = AnswerPacketBuilder().build(context={}, tool_state=state)

    assert packet.sources[0].reference == excerpt
    assert packet.coverage.rejected_sources == 0


def test_external_source_provenance_tampering_is_rejected() -> None:
    arguments = {"url": "https://example.org/paper"}
    payload = {"content": "Verified content"}
    source = extract_external_sources(arguments=arguments, payload=payload)[0]
    assert source.provenance is not None
    forged = replace(
        source,
        provenance=replace(source.provenance, excerpt_start=1),
    )
    state = ToolRunState()
    state.add_tool_outcome(
        ToolCall(id="remote", name="extract", args=arguments),
        ToolOutcome(payload=payload, sources=(forged,)),
    )

    packet = AnswerPacketBuilder().build(context={}, tool_state=state)

    assert packet.sources == []
    assert packet.coverage.rejected_sources == 1


def test_external_source_keeps_distinct_excerpts_from_the_same_url() -> None:
    sources = extract_external_sources(
        arguments={"query": "test"},
        payload={
            "results": [
                {"url": "https://example.org/paper", "snippet": "First result"},
                {"url": "https://example.org/paper", "snippet": "Second result"},
            ]
        },
    )

    assert [source.excerpt for source in sources] == ["First result", "Second result"]


def test_plain_text_search_results_bind_each_url_to_its_local_result_block() -> None:
    payload = """## Search Results

### 1. First Paper
- **URL**: https://example.org/first
- First paper finding.

### 2. Second Paper
- **URL**: https://example.org/second
- Second paper finding.
"""

    sources = extract_external_sources(arguments={"query": "test"}, payload=payload)

    by_url = {source.url: source for source in sources}
    first = by_url["https://example.org/first"]
    second = by_url["https://example.org/second"]
    assert first.title == "First Paper"
    assert second.title == "Second Paper"
    assert first.excerpt is not None and "First paper finding" in first.excerpt
    assert "Second paper finding" not in first.excerpt
    assert second.excerpt is not None and "Second paper finding" in second.excerpt
    assert "First paper finding" not in second.excerpt


def test_external_source_never_uses_argument_text_as_excerpt() -> None:
    sources = extract_external_sources(
        arguments={
            "url": "https://example.org/paper",
            "content": "Caller-controlled text",
        },
        payload={"status": 200},
    )

    assert len(sources) == 1
    assert sources[0].excerpt is None


def test_observation_cannot_register_external_url_absent_from_tool_data() -> None:
    state = ToolRunState()
    state.add_tool_outcome(
        ToolCall(id="remote", name="research", args={"query": "test"}),
        ToolOutcome(
            payload={"result": "No source URL was returned"},
            sources=(
                ExternalSourceCandidate(
                    url="https://forged.example/source",
                    excerpt="No source URL was returned",
                ),
            ),
        ),
    )

    packet = AnswerPacketBuilder().build(context={}, tool_state=state)

    assert packet.sources == []
    assert packet.coverage.rejected_sources == 1


def test_grounded_answer_parser_handles_every_chunk_boundary() -> None:
    source = ExternalAnswerSource(
        key=7,
        url="https://example.org/paper",
        title="Paper",
        reference="Verified excerpt",
    )
    nonce = "fixed"
    value = "Intro.\n\nGrounded 🧠 claim.[[SCHOLENS_CITE:fixed:7]] End."
    for split in range(len(value) + 1):
        parser = GroundedAnswerStreamParser([source], nonce=nonce)
        rendered = parser.feed(value[:split]) + parser.feed(value[split:])
        rendered += parser.finish()
        assert rendered == "Intro.\n\nGrounded 🧠 claim. End."
        references = parser.references()
        assert references is not None
        assert references.sources[0].key == 1
        assert references.annotations[0].source_keys == [1]
        assert (
            rendered[
                references.annotations[0].start_offset : references.annotations[
                    0
                ].end_offset
            ]
            == "Grounded 🧠 claim."
        )


def test_grounded_answer_parser_keeps_text_for_invalid_or_unclosed_frames() -> None:
    source = ExternalAnswerSource(
        key=1,
        url="https://example.org/paper",
        reference="Verified excerpt",
    )
    parser = GroundedAnswerStreamParser([source], nonce="fixed")
    rendered = parser.feed(
        "Unsupported[[SCHOLENS_CITE:fixed:99]] Unclosed[[SCHOLENS_CITE:fixed:1"
    )
    rendered += parser.finish()

    assert rendered == "Unsupported Unclosed"
    assert parser.references() is None
    assert parser.metrics().invalid_source_keys == 1
    assert parser.metrics().protocol_errors == 1


def test_grounded_answer_parser_never_leaks_an_incomplete_opening_frame() -> None:
    parser = GroundedAnswerStreamParser([], nonce="fixed")

    rendered = parser.feed("Visible [[SCHOLENS_CITE:fixed:1") + parser.finish()

    assert rendered == "Visible "
    assert parser.metrics().protocol_errors == 1


def test_grounded_answer_parser_strips_marker_with_missing_nonce() -> None:
    source = ExternalAnswerSource(
        key=1,
        url="https://example.org/paper",
        reference="Verified excerpt",
    )
    parser = GroundedAnswerStreamParser([source], nonce="fixed")

    rendered = parser.feed("Claim.[[SCHOLENS_CITE:1]]") + parser.finish()

    assert rendered == "Claim."
    assert parser.references() is None
    assert parser.metrics().protocol_errors == 1


def test_grounded_answer_parser_accepts_provider_normalized_single_brackets() -> None:
    source = ExternalAnswerSource(
        key=7,
        url="https://example.org/paper",
        reference="Verified excerpt",
    )
    value = "Grounded claim.[SCHOLENS_CITE:fixed:7] End."

    for split in range(len(value) + 1):
        parser = GroundedAnswerStreamParser([source], nonce="fixed")
        rendered = parser.feed(value[:split]) + parser.feed(value[split:])
        rendered += parser.finish()
        references = parser.references()

        assert rendered == "Grounded claim. End."
        assert references is not None
        assert references.annotations[0].source_keys == [1]
        assert (
            rendered[
                references.annotations[0].start_offset : references.annotations[
                    0
                ].end_offset
            ]
            == "Grounded claim."
        )


def test_grounded_answer_parser_maps_each_marker_to_the_preceding_passage() -> None:
    sources = [
        ExternalAnswerSource(
            key=key,
            url=f"https://example.org/{key}",
            reference=f"Excerpt {key}",
        )
        for key in (3, 8)
    ]
    parser = GroundedAnswerStreamParser(sources, nonce="fixed")
    rendered = parser.feed(
        "First claim.[[SCHOLENS_CITE:fixed:3]] Second claim.[[SCHOLENS_CITE:fixed:8,3]]"
    )
    rendered += parser.finish()

    assert rendered == "First claim. Second claim."
    references = parser.references()
    assert references is not None
    assert [
        rendered[item.start_offset : item.end_offset] for item in references.annotations
    ] == ["First claim.", "Second claim."]
    assert references.annotations[0].source_keys == [1]
    assert references.annotations[1].source_keys == [2, 1]


def test_paper_summary_markers_are_materialized_before_conversation_storage() -> None:
    document_id = uuid4()
    content, references = materialize_summary_references(
        "The method is efficient [^4].\n\nA second claim [^8, ^4].",
        [
            ResponseCitation(index=4, text="Method excerpt"),
            ResponseCitation(index=8, text="Second excerpt"),
        ],
        document_id=document_id,
        title="Paper",
    )

    assert "[^" not in content
    assert references is not None
    assert [source.key for source in references.sources] == [1, 2]
    assert references.annotations[0].source_keys == [1]
    assert references.annotations[1].source_keys == [2, 1]
    for annotation in references.annotations:
        assert content[annotation.start_offset : annotation.end_offset].strip()


def test_answer_packet_reports_every_kind_of_budget_truncation(monkeypatch) -> None:
    from app.llm import answer_packet as answer_packet_module

    monkeypatch.setattr(answer_packet_module, "ANSWER_PACKET_TOKEN_BUDGET", 1_200)
    monkeypatch.setattr(answer_packet_module, "_CONTEXT_TOKEN_BUDGET", 150)
    monkeypatch.setattr(answer_packet_module, "_MATERIAL_TOKEN_BUDGET", 300)
    monkeypatch.setattr(answer_packet_module, "_ACTION_TOKEN_BUDGET", 150)
    monkeypatch.setattr(answer_packet_module, "_SOURCE_TOKEN_BUDGET", 300)
    document_id = uuid4()
    state = ToolRunState()
    state.add_tool_outcome(
        ToolCall(id="read", name="get_paper_content", args={}),
        ToolOutcome(
            payload={"content": "m" * 3_000},
            sources=(
                DocumentSourceCandidate(
                    document_id=document_id,
                    excerpt="s" * 3_000,
                ),
            ),
        ),
    )
    state.add_tool_outcome(
        ToolCall(id="create", name="create_project", args={}),
        ToolOutcome(
            payload={"project_id": "project-1"},
            action={"kind": "project_created", "detail": "a" * 3_000},
        ),
    )

    packet = answer_packet_module.AnswerPacketBuilder().build(
        context={"papers": "c" * 3_000},
        tool_state=state,
        document_source_texts={document_id: ("s" * 3_000,)},
    )

    assert answer_packet_module.estimate_tokens(packet.model_dump_json()) <= 1_200
    assert packet.coverage.context_truncated is True
    assert packet.coverage.truncated_observations == 1
    assert packet.coverage.truncated_materials == 0
    assert packet.coverage.truncated_sources == 1
    assert packet.coverage.truncated_actions == 1


def test_answer_packet_fairly_omits_materials_when_metadata_exceeds_budget(
    monkeypatch,
) -> None:
    from app.llm import answer_packet as answer_packet_module

    monkeypatch.setattr(answer_packet_module, "ANSWER_PACKET_TOKEN_BUDGET", 900)
    monkeypatch.setattr(answer_packet_module, "_CONTEXT_TOKEN_BUDGET", 50)
    monkeypatch.setattr(answer_packet_module, "_MATERIAL_TOKEN_BUDGET", 300)
    monkeypatch.setattr(answer_packet_module, "_ACTION_TOKEN_BUDGET", 50)
    monkeypatch.setattr(answer_packet_module, "_SOURCE_TOKEN_BUDGET", 300)
    state = ToolRunState()
    for index in range(100):
        state.add_tool_outcome(
            ToolCall(id=str(index), name="search", args={}),
            ToolOutcome(payload={"index": index, "value": "x" * 30}),
        )

    packet = answer_packet_module.AnswerPacketBuilder().build(
        context={},
        tool_state=state,
    )

    assert answer_packet_module.estimate_tokens(packet.model_dump_json()) <= 900
    assert 0 < len(packet.materials) < 100
    assert packet.materials[0].id == "o0-0"
    assert int(packet.materials[-1].id.removeprefix("o").split("-", 1)[0]) > 50
    assert packet.coverage.truncated_materials == 100 - len(packet.materials)
    assert packet.coverage.truncated_observations == 100
