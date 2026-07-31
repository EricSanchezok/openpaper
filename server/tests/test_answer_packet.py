from uuid import uuid4

from app.llm.answer_packet import AnswerPacketBuilder, CitationMarkerFilter
from app.modules.conversations.application.contracts.messages import ToolRunState
from app.modules.papers.application.contracts.extraction import ToolCall
from app.tooling import (
    DocumentSourceCandidate,
    ExternalSourceCandidate,
    ToolOutcome,
)
from app.tooling.source_extraction import extract_external_sources


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


def test_external_url_argument_is_bound_to_result_excerpt_not_to_itself() -> None:
    sources = extract_external_sources(
        arguments={"url": "https://example.org/paper"},
        payload={"content": "The returned page supports the result."},
    )

    assert len(sources) == 1
    assert sources[0].url == "https://example.org/paper"
    assert sources[0].excerpt == "The returned page supports the result."


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


def test_citation_filter_handles_chunk_boundaries_and_only_hides_source_identity() -> None:
    document_id = uuid4()
    source = ExternalSourceCandidate(
        url="https://example.org/paper",
        title="Paper",
        excerpt="Verified excerpt",
    )
    packet = AnswerPacketBuilder().build(
        context={},
        tool_state=ToolRunState(),
        direct_sources=[
            source,
            DocumentSourceCandidate(
                document_id=document_id,
                excerpt="Document excerpt",
            ),
        ],
        document_source_texts={document_id: ("Document excerpt",)},
    )
    citation_filter = CitationMarkerFilter(packet.sources)

    chunks = [
        "Supported [^",
        "1], unknown [^99], source https://example.org/paper and document ",
        f"{document_id}. Project 123e4567-e89b-42d3-a456-426614174000 and ",
        "download https://downloads.example/file.pdf.",
    ]
    rendered = "".join(citation_filter.feed(chunk) for chunk in chunks)
    rendered += citation_filter.finish()

    assert "[^1]" in rendered
    assert "[^99]" not in rendered
    assert "https://example.org/paper" not in rendered
    assert str(document_id) not in rendered
    assert "123e4567-e89b-42d3-a456-426614174000" in rendered
    assert "https://downloads.example/file.pdf" in rendered
    references = citation_filter.references()
    assert references is not None
    assert [citation.key for citation in references.citations] == [1]


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
