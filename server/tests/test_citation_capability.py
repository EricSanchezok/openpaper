from uuid import uuid4

from app.main import app
from app.modules.papers.application.citations import ResolveCitation
from app.modules.papers.domain.citations import CitationFields
from app.shared.application import Actor


class CitationGateway:
    def __init__(self, fields: CitationFields) -> None:
        self.fields = fields
        self.hydrate_calls = 0
        self.recover_calls = 0

    def read(self, **_kwargs: object) -> CitationFields:
        return self.fields

    def hydrate(self, **_kwargs: object) -> CitationFields:
        self.hydrate_calls += 1
        return self.fields

    def recover(
        self, **_kwargs: object
    ) -> tuple[CitationFields, dict[str, object], float | None]:
        self.recover_calls += 1
        return self.fields, {}, None


def actor() -> Actor:
    return Actor(
        id=7,
        email="reader@example.com",
        status="active",
        email_verified=True,
        is_active=True,
    )


def test_cached_citation_does_not_call_external_metadata_paths() -> None:
    gateway = CitationGateway(
        CitationFields(
            title="A Paper",
            authors=["A. Author"],
            publish_date="2025-01-01",
            journal="Journal",
        )
    )

    result = ResolveCitation(gateway)(actor=actor(), document_id=uuid4(), style="APA")

    assert result.method == "cached"
    assert result.data.title == "A Paper"
    assert gateway.hydrate_calls == 0
    assert gateway.recover_calls == 0


def test_citation_is_one_shared_public_paper_capability() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/papers/{document_id}/citation" in paths
    assert (
        paths["/api/v1/papers/{document_id}/citation"]["get"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/CitationResult"
    )
