"""Project collaboration use cases shared by inbound transports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.papers.application.downloads import PaperDownloadSigner
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
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind


@dataclass(frozen=True, slots=True)
class InvitationDelivery:
    response: ProjectInvitationResponse
    recipient_email: str
    project_title: str
    raw_token: str


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
    ) -> ProjectResponse: ...

    def delete(self, *, user_id: int, project_id: UUID) -> None: ...

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
    ) -> ProjectCollaboratorResponse: ...

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
    ) -> None: ...

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
    ) -> None: ...

    def collect_document(
        self,
        *,
        actor: Actor,
        request: CollectPaperFromProjectRequest,
    ) -> UUID | None: ...

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
    ) -> None: ...


class ProjectCapacity(Protocol):
    def require_create(self, *, actor: Actor) -> None: ...


class ProjectEvents(Protocol):
    def record(
        self,
        *,
        actor: Actor,
        name: str,
        properties: dict[str, object] | None = None,
    ) -> None: ...


class ProjectInvitationNotifier(Protocol):
    def send(self, *, inviter: Actor, delivery: InvitationDelivery) -> None: ...


class Projects:
    def __init__(
        self,
        *,
        gateway: ProjectGateway,
        capacity: ProjectCapacity,
        events: ProjectEvents,
        invitations: ProjectInvitationNotifier,
        signer: PaperDownloadSigner,
    ) -> None:
        self._gateway = gateway
        self._capacity = capacity
        self._events = events
        self._invitations = invitations
        self._signer = signer

    def create(self, *, actor: Actor, request: ProjectCreateRequest) -> ProjectResponse:
        self._capacity.require_create(actor=actor)
        result = self._gateway.create(owner_id=actor.id, request=request)
        self._events.record(actor=actor, name="project_created")
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
        project_id: UUID,
        request: ProjectUpdateRequest,
    ) -> ProjectResponse:
        result = self._gateway.update(
            user_id=actor.id,
            project_id=project_id,
            request=request,
        )
        self._events.record(actor=actor, name="project_updated")
        return result

    def delete(self, *, actor: Actor, project_id: UUID) -> None:
        self._gateway.delete(user_id=actor.id, project_id=project_id)
        self._events.record(actor=actor, name="project_deleted")

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
        project_id: UUID,
        user_id: int,
        request: ProjectCollaboratorUpdateRequest,
    ) -> ProjectCollaboratorResponse:
        return self._gateway.update_member(
            actor_id=actor.id,
            project_id=project_id,
            user_id=user_id,
            request=request,
        )

    def remove_member(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        user_id: int,
    ) -> None:
        self._gateway.remove_member(
            actor_id=actor.id,
            project_id=project_id,
            user_id=user_id,
        )

    def leave(self, *, actor: Actor, project_id: UUID) -> None:
        self._gateway.leave(user_id=actor.id, project_id=project_id)

    def transfer(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        request: ProjectTransferRequest,
    ) -> ProjectResponse:
        return self._gateway.transfer(
            owner_id=actor.id,
            project_id=project_id,
            request=request,
        )

    def accept_invitation(self, *, actor: Actor, raw_token: str) -> None:
        self._gateway.accept_invitation(
            raw_token=raw_token,
            user_id=actor.id,
            email=actor.email,
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
        project_id: UUID,
        request: ProjectInvitationCreateRequest,
    ) -> ProjectInvitationResponse:
        delivery = self._gateway.create_invitation(
            actor_id=actor.id,
            project_id=project_id,
            request=request,
        )
        self._invitations.send(inviter=actor, delivery=delivery)
        return delivery.response

    def resend_invitation(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        invitation_id: UUID,
    ) -> ProjectInvitationResponse:
        delivery = self._gateway.resend_invitation(
            actor_id=actor.id,
            project_id=project_id,
            invitation_id=invitation_id,
        )
        self._invitations.send(inviter=actor, delivery=delivery)
        return delivery.response

    def revoke_invitation(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        invitation_id: UUID,
    ) -> None:
        self._gateway.revoke_invitation(
            actor_id=actor.id,
            project_id=project_id,
            invitation_id=invitation_id,
        )

    def collect_document(
        self,
        *,
        actor: Actor,
        request: CollectPaperFromProjectRequest,
    ) -> ProjectPaperCollectedResponse:
        document_id = self._gateway.collect_document(actor=actor, request=request)
        if document_id is None:
            raise AppError(
                code="project_document_not_found",
                message="Document not found in this Project",
                kind=FailureKind.NOT_FOUND,
            )
        self._events.record(
            actor=actor,
            name="paper_collected_from_project",
            properties={
                "source_project_id": str(request.source_project_id),
                "document_id": str(request.document_id),
            },
        )
        return ProjectPaperCollectedResponse(document_id=document_id)

    def add_documents(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        request: AddPaperToProjectRequest,
    ) -> ProjectPapersAddedResponse:
        added_count, existing_count = self._gateway.add_documents(
            actor=actor,
            project_id=project_id,
            request=request,
        )
        self._events.record(
            actor=actor,
            name="papers_added_to_project",
            properties={
                "project_id": str(project_id),
                "added_count": added_count,
                "existing_count": existing_count,
            },
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
        project_id: UUID,
        document_id: UUID,
    ) -> None:
        self._gateway.remove_document(
            actor=actor,
            project_id=project_id,
            document_id=document_id,
        )
        self._events.record(actor=actor, name="paper_removed_from_project")
