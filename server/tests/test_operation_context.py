from __future__ import annotations

from collections.abc import Iterator
from dataclasses import FrozenInstanceError
from uuid import UUID, uuid4

import pytest
from app.shared.application.operation_context import (
    ConversationOrigin,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    JobOrigin,
    McpOrigin,
    OAuthCallbackOrigin,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
    SchedulerOrigin,
    WebhookOrigin,
)

DIGEST = "a" * 64


def _uuid_generator(values: Iterator[UUID]) -> UUID:
    return next(values)


def _factory(*values: UUID) -> OperationContextFactory:
    generated = iter(values)
    return OperationContextFactory(lambda: _uuid_generator(generated))


def _request() -> RequestReference:
    return RequestReference(uuid4())


@pytest.mark.parametrize(
    ("initiated_by", "origin", "credential"),
    [
        (
            OperationInitiator.USER,
            HttpOrigin(_request()),
            CredentialRef(CredentialKind.CLOUD_SESSION),
        ),
        (
            OperationInitiator.USER,
            ConversationOrigin(_request(), uuid4(), uuid4()),
            CredentialRef(CredentialKind.CLOUD_SESSION),
        ),
        (
            OperationInitiator.AGENT,
            McpOrigin(_request(), DIGEST, DIGEST),
            CredentialRef(CredentialKind.ACCESS_KEY, str(uuid4())),
        ),
        (
            OperationInitiator.SYSTEM,
            JobOrigin(uuid4(), DIGEST, uuid4()),
            CredentialRef(CredentialKind.INTERNAL_SIGNATURE, "jobs-v1"),
        ),
        (
            OperationInitiator.SYSTEM,
            JobOrigin(uuid4(), None, None),
            None,
        ),
        (
            OperationInitiator.SYSTEM,
            WebhookOrigin(_request(), "stripe", DIGEST),
            CredentialRef(CredentialKind.PROVIDER_SIGNATURE, "stripe-v1"),
        ),
        (
            OperationInitiator.SYSTEM,
            OAuthCallbackOrigin(_request(), "zotero"),
            None,
        ),
        (
            OperationInitiator.SYSTEM,
            SchedulerOrigin("document_gc", uuid4()),
            None,
        ),
    ],
)
def test_factory_accepts_each_root_boundary(
    initiated_by: OperationInitiator,
    origin: object,
    credential: CredentialRef | None,
) -> None:
    operation_id = uuid4()
    operation = _factory(operation_id).root(
        initiated_by=initiated_by,
        origin=origin,  # type: ignore[arg-type]
        credential=credential,
    )

    assert operation.trace.operation_id == operation_id
    assert operation.trace.correlation_id == operation_id
    assert operation.trace.causation_id is None


@pytest.mark.parametrize(
    ("initiated_by", "origin", "credential"),
    [
        (OperationInitiator.AGENT, HttpOrigin(_request()), None),
        (
            OperationInitiator.USER,
            McpOrigin(_request(), None, DIGEST),
            CredentialRef(CredentialKind.ACCESS_KEY, str(uuid4())),
        ),
        (
            OperationInitiator.SYSTEM,
            WebhookOrigin(_request(), "stripe", None),
            CredentialRef(CredentialKind.INTERNAL_SIGNATURE),
        ),
        (
            OperationInitiator.SYSTEM,
            OAuthCallbackOrigin(_request(), "zotero"),
            CredentialRef(CredentialKind.CLOUD_SESSION),
        ),
    ],
)
def test_factory_rejects_contradictory_root_provenance(
    initiated_by: OperationInitiator,
    origin: object,
    credential: CredentialRef | None,
) -> None:
    with pytest.raises(ValueError):
        _factory(uuid4()).root(
            initiated_by=initiated_by,
            origin=origin,  # type: ignore[arg-type]
            credential=credential,
        )


def test_child_and_resume_preserve_explicit_causality() -> None:
    root_id, child_id, resumed_id = uuid4(), uuid4(), uuid4()
    factory = _factory(root_id, child_id, resumed_id)
    root = factory.root(
        initiated_by=OperationInitiator.USER,
        origin=ConversationOrigin(_request(), uuid4(), uuid4()),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )

    child = factory.child(root, initiated_by=OperationInitiator.AGENT)
    resumed = factory.resume(
        correlation_id=root.trace.correlation_id,
        causation_id=child.trace.operation_id,
        initiated_by=OperationInitiator.SYSTEM,
        origin=JobOrigin(uuid4(), None, None),
        credential=None,
    )

    assert child.trace.operation_id == child_id
    assert child.trace.correlation_id == root_id
    assert child.trace.causation_id == root_id
    assert child.credential == root.credential
    assert resumed.trace.operation_id == resumed_id
    assert resumed.trace.correlation_id == root_id
    assert resumed.trace.causation_id == child_id


def test_http_model_work_can_be_attributed_to_an_agent_child() -> None:
    root_id, child_id = uuid4(), uuid4()
    factory = _factory(root_id, child_id)
    root = factory.root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(_request()),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )

    child = factory.child(root, initiated_by=OperationInitiator.AGENT)

    assert child.trace.operation_id == child_id
    assert child.trace.causation_id == root_id
    assert child.initiated_by is OperationInitiator.AGENT


def test_child_cannot_switch_origin_or_credential() -> None:
    factory = _factory(uuid4(), uuid4())
    root = factory.root(
        initiated_by=OperationInitiator.USER,
        origin=ConversationOrigin(_request(), uuid4(), uuid4()),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )

    with pytest.raises(ValueError, match="retain its parent origin"):
        factory.child(
            root,
            initiated_by=OperationInitiator.AGENT,
            origin=ConversationOrigin(_request(), uuid4(), uuid4()),
        )


def test_context_is_immutable_and_credential_repr_is_safe() -> None:
    credential_id = str(uuid4())
    context = _factory(uuid4()).root(
        initiated_by=OperationInitiator.AGENT,
        origin=McpOrigin(_request(), None, DIGEST),
        credential=CredentialRef(CredentialKind.ACCESS_KEY, credential_id),
    )

    assert credential_id not in repr(context)
    with pytest.raises(FrozenInstanceError):
        context.trace = context.trace  # type: ignore[misc]


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: McpOrigin(_request(), None, "not-a-digest"),
        lambda: WebhookOrigin(_request(), "Stripe API", None),
        lambda: SchedulerOrigin("Document GC", uuid4()),
        lambda: CredentialRef(CredentialKind.CLOUD_SESSION, "unsafe"),
        lambda: CredentialRef(CredentialKind.ACCESS_KEY, "not-a-uuid"),
    ],
)
def test_typed_values_reject_unbounded_or_sensitive_references(
    constructor: object,
) -> None:
    with pytest.raises(ValueError):
        constructor()  # type: ignore[operator]
