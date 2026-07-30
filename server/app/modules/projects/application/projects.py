"""Project collaboration use cases shared by inbound transports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from app.modules.papers.application.downloads import PaperDownloadSigner
from app.modules.jobs.application.actions import JOB_CREATED
from app.modules.projects.application.contracts import (
    AddPaperToProjectRequest,
    CollectPaperFromProjectRequest,
    ProjectCollaboratorListResponse,
    ProjectCollaboratorResponse,
    ProjectCollaboratorUpdateRequest,
    ProjectCreateRequest,
    ProjectInvitationCreateRequest,
    ProjectInvitationListResponse,
    ProjectInvitationResponse,
    ProjectListResponse,
    ProjectPaperCollectedResponse,
    ProjectPaperFileUrlResponse,
    ProjectPaperListResponse,
    ProjectPapersAddedResponse,
    ProjectPendingUploadsResponse,
    ProjectResponse,
    ProjectTransferRequest,
    ProjectUpdateRequest,
)
from app.modules.projects.application.actions import (
    PROJECT_COLLABORATOR_LEFT,
    PROJECT_COLLABORATOR_REMOVED,
    PROJECT_COLLABORATOR_UPDATED,
    PROJECT_CREATED,
    PROJECT_DELETED,
    PROJECT_INVITATION_ACCEPTED,
    PROJECT_INVITATION_CREATED,
    PROJECT_INVITATION_RESENT,
    PROJECT_INVITATION_REVOKED,
    PROJECT_OWNERSHIP_TRANSFERRED,
    PROJECT_PAPER_COLLECTED,
    PROJECT_PAPER_REMOVED,
    PROJECT_PAPERS_ADDED,
    PROJECT_UPDATED,
)
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import (
    OperationChange,
    ResourceRef,
)
from app.shared.application import Actor
from app.shared.application.operation_context import OperationContext
from app.shared.domain import AppError, FailureKind


@dataclass(frozen=True, slots=True)
class InvitationDelivery:
    response: ProjectInvitationResponse
    recipient_email: str
    project_title: str
    raw_token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProjectUpdateResult:
    response: ProjectResponse
    changed: bool


@dataclass(frozen=True, slots=True)
class ProjectCollaboratorUpdateResult:
    response: ProjectCollaboratorResponse
    changed: bool


@dataclass(frozen=True, slots=True)
class AcceptedProjectInvitation:
    project_id: UUID
    invitation_id: UUID


@dataclass(frozen=True, slots=True)
class ProjectDocumentCollection:
    document_id: UUID
    added_to_library: bool


@dataclass(frozen=True, slots=True)
class ProjectDeletion:
    created_cleanup_job_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class ProjectPaperRemoval:
    created_gc_job_id: UUID | None


class ProjectGateway(Protocol):
    def create(
        self,
        *,
        owner_id: int,
        request: ProjectCreateRequest,
    ) -> ProjectResponse: ...

    def list_projects(
        self,
        *,
        user_id: int,
        limit: int | None,
    ) -> list[ProjectResponse]: ...

    def get(self, *, user_id: int, project_id: UUID) -> ProjectResponse: ...

    def update(
        self,
        *,
        user_id: int,
        project_id: UUID,
        request: ProjectUpdateRequest,
    ) -> ProjectUpdateResult: ...

    def delete(
        self,
        *,
        user_id: int,
        project_id: UUID,
        origin_operation_id: UUID,
        correlation_id: UUID,
    ) -> ProjectDeletion: ...

    def list_members(
        self,
        *,
        user_id: int,
        project_id: UUID,
    ) -> list[ProjectCollaboratorResponse]: ...

    def update_member(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        user_id: int,
        request: ProjectCollaboratorUpdateRequest,
    ) -> ProjectCollaboratorUpdateResult: ...

    def remove_member(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        user_id: int,
    ) -> None: ...

    def leave(self, *, user_id: int, project_id: UUID) -> None: ...

    def transfer(
        self,
        *,
        owner_id: int,
        project_id: UUID,
        request: ProjectTransferRequest,
    ) -> ProjectResponse: ...

    def accept_invitation(
        self,
        *,
        raw_token: str,
        user_id: int,
        email: str,
    ) -> AcceptedProjectInvitation: ...

    def list_invitations(
        self,
        *,
        actor_id: int,
        project_id: UUID,
    ) -> list[ProjectInvitationResponse]: ...

    def create_invitation(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        request: ProjectInvitationCreateRequest,
    ) -> InvitationDelivery: ...

    def resend_invitation(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        invitation_id: UUID,
    ) -> InvitationDelivery: ...

    def revoke_invitation(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        invitation_id: UUID,
    ) -> bool: ...

    def collect_document(
        self,
        *,
        actor: Actor,
        request: CollectPaperFromProjectRequest,
    ) -> ProjectDocumentCollection | None: ...

    def add_documents(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        request: AddPaperToProjectRequest,
    ) -> tuple[int, int]: ...

    def list_documents(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        load_urls: bool,
    ) -> ProjectPaperListResponse: ...

    def pending_uploads(
        self,
        *,
        actor: Actor,
        project_id: UUID,
    ) -> ProjectPendingUploadsResponse: ...

    def document_storage_key(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        document_id: UUID,
    ) -> str | None: ...

    def projects_for_document(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> list[ProjectResponse]: ...

    def remove_document(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        document_id: UUID,
        origin_operation_id: UUID,
        correlation_id: UUID,
    ) -> ProjectPaperRemoval: ...


class ProjectCapacity(Protocol):
    def require_create(self, *, actor: Actor) -> None: ...


class Projects:
    def __init__(
        self,
        *,
        gateway: ProjectGateway,
        capacity: ProjectCapacity,
        signer: PaperDownloadSigner,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._capacity = capacity
        self._signer = signer
        self._journal = journal

    def create(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request: ProjectCreateRequest,
    ) -> ProjectResponse:
        self._capacity.require_create(actor=actor)
        result = self._gateway.create(owner_id=actor.id, request=request)
        self._journal.append(
            actor=actor,
            operation=operation,
            action=PROJECT_CREATED,
            resources=(ResourceRef(type="project", id=str(result.id)),),
        )
        return result

    def list(
        self,
        *,
        actor: Actor,
        limit: int | None,
    ) -> ProjectListResponse:
        return ProjectListResponse(
            items=self._gateway.list_projects(user_id=actor.id, limit=limit)
        )

    def get(self, *, actor: Actor, project_id: UUID) -> ProjectResponse:
        return self._gateway.get(user_id=actor.id, project_id=project_id)

    def update(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        request: ProjectUpdateRequest,
    ) -> ProjectResponse:
        result = self._gateway.update(
            user_id=actor.id,
            project_id=project_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=PROJECT_UPDATED,
                resources=(ResourceRef(type="project", id=str(project_id)),),
            )
        return result.response

    def delete(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
    ) -> None:
        result = self._gateway.delete(
            user_id=actor.id,
            project_id=project_id,
            origin_operation_id=operation.trace.operation_id,
            correlation_id=operation.trace.correlation_id,
        )
        changes = [
            OperationChange(
                action=PROJECT_DELETED,
                resources=(ResourceRef(type="project", id=str(project_id)),),
            ),
            *(
                OperationChange(
                    action=JOB_CREATED,
                    resources=(ResourceRef(type="job", id=str(job_id)),),
                )
                for job_id in result.created_cleanup_job_ids
            ),
        ]
        self._journal.append_many(
            actor=actor,
            operation=operation,
            changes=changes,
        )

    def members(
        self,
        *,
        actor: Actor,
        project_id: UUID,
    ) -> ProjectCollaboratorListResponse:
        return ProjectCollaboratorListResponse(
            items=self._gateway.list_members(
                user_id=actor.id,
                project_id=project_id,
            )
        )

    def update_member(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        user_id: int,
        request: ProjectCollaboratorUpdateRequest,
    ) -> ProjectCollaboratorResponse:
        result = self._gateway.update_member(
            actor_id=actor.id,
            project_id=project_id,
            user_id=user_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=PROJECT_COLLABORATOR_UPDATED,
                resources=(
                    ResourceRef(type="project", id=str(project_id)),
                    ResourceRef(type="user", id=str(user_id)),
                ),
            )
        return result.response

    def remove_member(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        user_id: int,
    ) -> None:
        self._gateway.remove_member(
            actor_id=actor.id,
            project_id=project_id,
            user_id=user_id,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=PROJECT_COLLABORATOR_REMOVED,
            resources=(
                ResourceRef(type="project", id=str(project_id)),
                ResourceRef(type="user", id=str(user_id)),
            ),
        )

    def leave(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
    ) -> None:
        self._gateway.leave(user_id=actor.id, project_id=project_id)
        self._journal.append(
            actor=actor,
            operation=operation,
            action=PROJECT_COLLABORATOR_LEFT,
            resources=(
                ResourceRef(type="project", id=str(project_id)),
                ResourceRef(type="user", id=str(actor.id)),
            ),
        )

    def transfer(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        request: ProjectTransferRequest,
    ) -> ProjectResponse:
        result = self._gateway.transfer(
            owner_id=actor.id,
            project_id=project_id,
            request=request,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=PROJECT_OWNERSHIP_TRANSFERRED,
            resources=(
                ResourceRef(type="project", id=str(project_id)),
                ResourceRef(type="user", id=str(request.new_owner_id)),
            ),
        )
        return result

    def accept_invitation(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        raw_token: str,
    ) -> None:
        accepted = self._gateway.accept_invitation(
            raw_token=raw_token,
            user_id=actor.id,
            email=actor.email,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=PROJECT_INVITATION_ACCEPTED,
            resources=(
                ResourceRef(type="project", id=str(accepted.project_id)),
                ResourceRef(
                    type="project_invitation",
                    id=str(accepted.invitation_id),
                ),
            ),
        )

    def invitations(
        self,
        *,
        actor: Actor,
        project_id: UUID,
    ) -> ProjectInvitationListResponse:
        return ProjectInvitationListResponse(
            items=self._gateway.list_invitations(
                actor_id=actor.id,
                project_id=project_id,
            )
        )

    def create_invitation(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        request: ProjectInvitationCreateRequest,
    ) -> InvitationDelivery:
        delivery = self._gateway.create_invitation(
            actor_id=actor.id,
            project_id=project_id,
            request=request,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=PROJECT_INVITATION_CREATED,
            resources=(
                ResourceRef(type="project", id=str(project_id)),
                ResourceRef(
                    type="project_invitation",
                    id=str(delivery.response.id),
                ),
            ),
        )
        return delivery

    def resend_invitation(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        invitation_id: UUID,
    ) -> InvitationDelivery:
        delivery = self._gateway.resend_invitation(
            actor_id=actor.id,
            project_id=project_id,
            invitation_id=invitation_id,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=PROJECT_INVITATION_RESENT,
            resources=(
                ResourceRef(type="project", id=str(project_id)),
                ResourceRef(type="project_invitation", id=str(invitation_id)),
                ResourceRef(
                    type="project_invitation",
                    id=str(delivery.response.id),
                ),
            ),
        )
        return delivery

    def revoke_invitation(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        invitation_id: UUID,
    ) -> None:
        changed = self._gateway.revoke_invitation(
            actor_id=actor.id,
            project_id=project_id,
            invitation_id=invitation_id,
        )
        if changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=PROJECT_INVITATION_REVOKED,
                resources=(
                    ResourceRef(type="project", id=str(project_id)),
                    ResourceRef(
                        type="project_invitation",
                        id=str(invitation_id),
                    ),
                ),
            )

    def collect_document(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request: CollectPaperFromProjectRequest,
    ) -> ProjectPaperCollectedResponse:
        result = self._gateway.collect_document(actor=actor, request=request)
        if result is None:
            raise AppError(
                code="project_document_not_found",
                message="Document not found in this Project",
                kind=FailureKind.NOT_FOUND,
            )
        if result.added_to_library:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=PROJECT_PAPER_COLLECTED,
                resources=(
                    ResourceRef(
                        type="project",
                        id=str(request.source_project_id),
                    ),
                    ResourceRef(type="document", id=str(result.document_id)),
                ),
            )
        return ProjectPaperCollectedResponse(document_id=result.document_id)

    def add_documents(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        request: AddPaperToProjectRequest,
    ) -> ProjectPapersAddedResponse:
        added_count, existing_count = self._gateway.add_documents(
            actor=actor,
            project_id=project_id,
            request=request,
        )
        if added_count:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=PROJECT_PAPERS_ADDED,
                resources=(ResourceRef(type="project", id=str(project_id)),),
            )
        return ProjectPapersAddedResponse(
            added_count=added_count,
            existing_count=existing_count,
        )

    def documents(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        load_urls: bool,
    ) -> ProjectPaperListResponse:
        return self._gateway.list_documents(
            actor=actor,
            project_id=project_id,
            load_urls=load_urls,
        )

    def pending_uploads(
        self,
        *,
        actor: Actor,
        project_id: UUID,
    ) -> ProjectPendingUploadsResponse:
        return self._gateway.pending_uploads(actor=actor, project_id=project_id)

    def document_download(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        document_id: UUID,
    ) -> ProjectPaperFileUrlResponse:
        storage_key = self._gateway.document_storage_key(
            actor=actor,
            project_id=project_id,
            document_id=document_id,
        )
        if storage_key is None:
            raise AppError(
                code="project_document_not_found",
                message="Document not found in this Project",
                kind=FailureKind.NOT_FOUND,
            )
        try:
            return ProjectPaperFileUrlResponse(
                file_url=self._signer.sign(storage_key=storage_key)
            )
        except RuntimeError as exc:
            raise AppError(
                code="document_file_url_unavailable",
                message="The document file is temporarily unavailable",
                kind=FailureKind.UNAVAILABLE,
            ) from exc

    def projects_for_document(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> ProjectListResponse:
        return ProjectListResponse(
            items=self._gateway.projects_for_document(
                actor=actor,
                document_id=document_id,
            )
        )

    def remove_document(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        document_id: UUID,
    ) -> None:
        result = self._gateway.remove_document(
            actor=actor,
            project_id=project_id,
            document_id=document_id,
            origin_operation_id=operation.trace.operation_id,
            correlation_id=operation.trace.correlation_id,
        )
        changes = [
            OperationChange(
                action=PROJECT_PAPER_REMOVED,
                resources=(
                    ResourceRef(type="project", id=str(project_id)),
                    ResourceRef(type="document", id=str(document_id)),
                ),
            )
        ]
        if result.created_gc_job_id is not None:
            changes.append(
                OperationChange(
                    action=JOB_CREATED,
                    resources=(
                        ResourceRef(type="job", id=str(result.created_gc_job_id)),
                    ),
                )
            )
        self._journal.append_many(
            actor=actor,
            operation=operation,
            changes=changes,
        )
