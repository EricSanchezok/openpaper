from __future__ import annotations

from datetime import datetime, timezone
from inspect import Parameter, signature
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationJournalEntry
from app.modules.papers.application.contracts.documents import (
    LibraryPaperUpdateRequest,
)
from app.modules.papers.application.contracts.tags import (
    LibraryTagAssignmentRequest,
)
from app.modules.papers.application.library import (
    LibraryPaperRemoval,
    LibraryPaperUpdateResult,
    PaperLibrary,
    PaperLibraryGateway,
)
from app.modules.papers.application.tags import LibraryTagGateway, LibraryTags
from app.modules.projects.application.contracts import (
    AddPaperToProjectRequest,
    ProjectResponse,
    ProjectUpdateRequest,
)
from app.modules.projects.application.projects import (
    ProjectDeletion,
    ProjectGateway,
    ProjectPaperRemoval,
    Projects,
    ProjectUpdateResult,
)
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)


class _Store:
    def __init__(self) -> None:
        self.entries: list[OperationJournalEntry] = []

    def append(self, entries: tuple[OperationJournalEntry, ...]) -> None:
        self.entries.extend(entries)


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 7, 30, 23, tzinfo=timezone.utc)


def _actor() -> Actor:
    return Actor(
        id=7,
        email="reader@example.com",
        status="active",
        email_verified=True,
    )


def _operation() -> OperationContext:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )


def _journal() -> tuple[OperationJournal, _Store]:
    store = _Store()
    return OperationJournal(store=store, clock=_Clock()), store


def _projects(
    gateway: object,
) -> tuple[Projects, _Store]:
    journal, store = _journal()
    return (
        Projects(
            gateway=cast(ProjectGateway, gateway),
            capacity=MagicMock(),
            signer=MagicMock(),
            journal=journal,
        ),
        store,
    )


def test_project_update_journals_only_a_real_change() -> None:
    project_id = uuid4()
    response = ProjectResponse.model_construct(id=project_id)
    gateway = MagicMock()
    gateway.update.side_effect = (
        ProjectUpdateResult(response=response, changed=False),
        ProjectUpdateResult(response=response, changed=True),
    )
    projects, store = _projects(gateway)
    actor = _actor()
    operation = _operation()
    request = ProjectUpdateRequest(title="Same title")

    assert (
        projects.update(
            actor=actor,
            operation=operation,
            project_id=project_id,
            request=request,
        )
        is response
    )
    assert store.entries == []

    projects.update(
        actor=actor,
        operation=operation,
        project_id=project_id,
        request=request,
    )
    assert [str(entry.action) for entry in store.entries] == ["project.updated"]


def test_project_bulk_add_skips_journal_when_every_paper_already_exists() -> None:
    project_id = uuid4()
    document_id = uuid4()
    gateway = MagicMock()
    gateway.add_documents.side_effect = ((0, 1), (1, 0))
    projects, store = _projects(gateway)
    actor = _actor()
    operation = _operation()
    request = AddPaperToProjectRequest(document_ids=[document_id])

    projects.add_documents(
        actor=actor,
        operation=operation,
        project_id=project_id,
        request=request,
    )
    assert store.entries == []

    projects.add_documents(
        actor=actor,
        operation=operation,
        project_id=project_id,
        request=request,
    )
    assert [str(entry.action) for entry in store.entries] == ["project.papers_added"]
    assert store.entries[0].resources[0].id == str(project_id)


def test_library_update_journals_only_user_visible_changes() -> None:
    document_id = uuid4()
    library_entry_id = uuid4()
    response = MagicMock(library_entry_id=library_entry_id)
    gateway = MagicMock()
    gateway.update.side_effect = (
        LibraryPaperUpdateResult(response=response, changed=False),
        LibraryPaperUpdateResult(response=response, changed=True),
    )
    journal, store = _journal()
    library = PaperLibrary(
        gateway=cast(PaperLibraryGateway, gateway),
        capacity=MagicMock(),
        signer=MagicMock(),
        journal=journal,
    )
    actor = _actor()
    operation = _operation()
    request = LibraryPaperUpdateRequest()

    assert (
        library.update(
            actor=actor,
            operation=operation,
            document_id=document_id,
            request=request,
        )
        is response
    )
    assert store.entries == []

    library.update(
        actor=actor,
        operation=operation,
        document_id=document_id,
        request=request,
    )
    assert [str(entry.action) for entry in store.entries] == ["library.paper_updated"]
    assert {resource.type for resource in store.entries[0].resources} == {
        "document",
        "library_paper",
    }


def test_library_remove_journals_only_a_new_cleanup_job() -> None:
    document_id = uuid4()
    gc_job_id = uuid4()
    gateway = MagicMock()
    gateway.remove.side_effect = (
        LibraryPaperRemoval(created_gc_job_id=None),
        LibraryPaperRemoval(created_gc_job_id=gc_job_id),
    )
    journal, store = _journal()
    library = PaperLibrary(
        gateway=cast(PaperLibraryGateway, gateway),
        capacity=MagicMock(),
        signer=MagicMock(),
        journal=journal,
    )

    library.remove(
        actor=_actor(),
        operation=_operation(),
        document_id=document_id,
    )
    assert [str(entry.action) for entry in store.entries] == ["library.paper_removed"]

    store.entries.clear()
    library.remove(
        actor=_actor(),
        operation=_operation(),
        document_id=document_id,
    )
    assert [str(entry.action) for entry in store.entries] == [
        "library.paper_removed",
        "job.created",
    ]
    assert store.entries[1].resources[0].id == str(gc_job_id)


def test_project_cleanup_jobs_are_journaled_only_when_created() -> None:
    project_id = uuid4()
    document_id = uuid4()
    delete_job_ids = (uuid4(), uuid4())
    document_gc_job_id = uuid4()
    gateway = MagicMock()
    gateway.delete.return_value = ProjectDeletion(
        created_cleanup_job_ids=delete_job_ids
    )
    gateway.remove_document.return_value = ProjectPaperRemoval(
        created_gc_job_id=document_gc_job_id
    )
    projects, store = _projects(gateway)

    projects.delete(
        actor=_actor(),
        operation=_operation(),
        project_id=project_id,
    )
    assert [str(entry.action) for entry in store.entries] == [
        "project.deleted",
        "job.created",
        "job.created",
    ]
    assert {entry.resources[0].id for entry in store.entries[1:]} == {
        str(job_id) for job_id in delete_job_ids
    }

    store.entries.clear()
    projects.remove_document(
        actor=_actor(),
        operation=_operation(),
        project_id=project_id,
        document_id=document_id,
    )
    assert [str(entry.action) for entry in store.entries] == [
        "project.paper_removed",
        "job.created",
    ]


def test_library_tag_assignment_uses_library_aggregate_and_skips_noop() -> None:
    gateway = MagicMock()
    gateway.assign.side_effect = (0, 2)
    journal, store = _journal()
    tags = LibraryTags(
        cast(LibraryTagGateway, gateway),
        journal=journal,
    )
    actor = _actor()
    operation = _operation()
    request = LibraryTagAssignmentRequest(
        document_ids=[uuid4()],
        tag_ids=[uuid4(), uuid4()],
    )

    tags.assign(actor=actor, operation=operation, request=request)
    assert store.entries == []

    tags.assign(actor=actor, operation=operation, request=request)
    assert [str(entry.action) for entry in store.entries] == ["library.tags_assigned"]
    assert store.entries[0].resources[0].type == "library"
    assert store.entries[0].resources[0].id == str(actor.id)


def test_workspace_commands_require_provenance_but_queries_do_not() -> None:
    commands = {
        Projects: {
            "create",
            "update",
            "delete",
            "update_member",
            "remove_member",
            "leave",
            "transfer",
            "accept_invitation",
            "create_invitation",
            "resend_invitation",
            "revoke_invitation",
            "collect_document",
            "add_documents",
            "remove_document",
        },
        PaperLibrary: {
            "update",
            "share",
            "unshare",
            "remove",
            "collect_public",
        },
        LibraryTags: {"create", "assign", "remove"},
    }
    queries = {
        Projects: {
            "list",
            "get",
            "members",
            "invitations",
            "documents",
            "pending_uploads",
            "document_download",
            "projects_for_document",
        },
        PaperLibrary: {"list", "get", "get_public"},
        LibraryTags: {"list"},
    }

    for service, method_names in commands.items():
        for method_name in method_names:
            parameter = signature(getattr(service, method_name)).parameters["operation"]
            assert parameter.kind is Parameter.KEYWORD_ONLY
    for service, method_names in queries.items():
        for method_name in method_names:
            assert (
                "operation" not in signature(getattr(service, method_name)).parameters
            )

    constructor_parameters = signature(Projects).parameters
    assert "events" not in constructor_parameters
    assert "invitations" not in constructor_parameters
