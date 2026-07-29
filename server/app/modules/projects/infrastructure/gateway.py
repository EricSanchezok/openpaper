"""SQLAlchemy and external-service adapters for Project use cases."""

from __future__ import annotations

from uuid import UUID

from app.database.models import AuthUser, Project, ProjectInvitation
from app.database.telemetry import track_event
from app.helpers.email import send_project_invite_email
from app.helpers.s3 import s3_service
from app.modules.papers.infrastructure.upload_repository import (
    upload_reservation_repository,
)
from app.modules.projects.application.contracts import (
    AddPaperToProjectRequest,
    CollectPaperFromProjectRequest,
    ProjectCollaboratorResponse,
    ProjectCollaboratorUpdateRequest,
    ProjectCreateRequest,
    ProjectInvitationCreateRequest,
    ProjectInvitationResponse,
    ProjectPaperListResponse,
    ProjectPaperSummaryResponse,
    ProjectPendingUploadResponse,
    ProjectPendingUploadsResponse,
    ProjectPermissionSet,
    ProjectResponse,
    ProjectTransferRequest,
    ProjectUpdateRequest,
)
from app.modules.projects.application.projects import InvitationDelivery
from app.modules.projects.infrastructure.document_repository import (
    project_document_repository,
)
from app.modules.projects.infrastructure.presenters import project_response
from app.modules.projects.infrastructure.repository import (
    CreatedInvitation,
    project_repository,
)
from app.shared.application import Actor
from sqlalchemy.orm import Session


def _collaborator_response(collaborator: object) -> ProjectCollaboratorResponse:
    from app.modules.projects.infrastructure.models import ProjectCollaborator

    if not isinstance(collaborator, ProjectCollaborator):
        raise TypeError("expected ProjectCollaborator")
    return ProjectCollaboratorResponse(
        user_id=collaborator.user_id,
        display_name=collaborator.user.display_name or collaborator.user.email,
        email=collaborator.user.email,
        is_owner=False,
        permissions=ProjectPermissionSet(
            edit_project=collaborator.can_edit_project,
            manage_papers=collaborator.can_manage_papers,
            manage_collaborators=collaborator.can_manage_collaborators,
        ),
        joined_at=collaborator.joined_at,
    )


class SqlAlchemyProjectGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _project(self, project: Project, *, user_id: int) -> ProjectResponse:
        return project_response(
            self._db,
            project=project,
            current_user_id=user_id,
        )

    def _invitation(self, invitation_id: UUID) -> ProjectInvitationResponse:
        invitation = self._db.get(ProjectInvitation, invitation_id)
        if invitation is None:
            raise RuntimeError("project_invitation_disappeared")
        project = self._db.get(Project, invitation.project_id)
        inviter = self._db.get(AuthUser, invitation.invited_by_id)
        if project is None or inviter is None:
            raise RuntimeError("project_invitation_relationship_missing")
        return ProjectInvitationResponse(
            id=invitation.id,
            project_id=invitation.project_id,
            project_name=project.title,
            email=invitation.email,
            invited_by=inviter.display_name or inviter.email,
            permissions=ProjectPermissionSet(
                edit_project=invitation.can_edit_project,
                manage_papers=invitation.can_manage_papers,
                manage_collaborators=invitation.can_manage_collaborators,
            ),
            expires_at=invitation.expires_at,
            created_at=invitation.created_at,
        )

    def _delivery(self, created: CreatedInvitation) -> InvitationDelivery:
        response = self._invitation(created.invitation.id)
        return InvitationDelivery(
            response=response,
            recipient_email=response.email,
            project_title=response.project_name,
            raw_token=created.raw_token,
        )

    def create(
        self,
        *,
        owner_id: int,
        request: ProjectCreateRequest,
    ) -> ProjectResponse:
        project = project_repository.create(
            self._db,
            owner_id=owner_id,
            title=request.title,
            description=request.description,
        )
        return self._project(project, user_id=owner_id)

    def list_projects(
        self,
        *,
        user_id: int,
        limit: int | None,
    ) -> list[ProjectResponse]:
        return [
            self._project(project, user_id=user_id)
            for project in project_repository.list_accessible(
                self._db,
                user_id=user_id,
                limit=limit,
            )
        ]

    def get(self, *, user_id: int, project_id: UUID) -> ProjectResponse:
        access = project_repository.get_access(
            self._db,
            project_id=project_id,
            user_id=user_id,
        )
        return self._project(access.project, user_id=user_id)

    def update(
        self,
        *,
        user_id: int,
        project_id: UUID,
        request: ProjectUpdateRequest,
    ) -> ProjectResponse:
        project = project_repository.update(
            self._db,
            project_id=project_id,
            user_id=user_id,
            changes=request.model_dump(exclude_unset=True),
        )
        return self._project(project, user_id=user_id)

    def delete(self, *, user_id: int, project_id: UUID) -> None:
        project_repository.delete(
            self._db,
            project_id=project_id,
            user_id=user_id,
        )

    def list_members(
        self,
        *,
        user_id: int,
        project_id: UUID,
    ) -> list[ProjectCollaboratorResponse]:
        project, collaborators = project_repository.list_collaborators(
            self._db,
            project_id=project_id,
            user_id=user_id,
        )
        owner = self._db.get(AuthUser, project.owner_id)
        if owner is None:
            raise RuntimeError("project_owner_missing")
        return [
            ProjectCollaboratorResponse(
                user_id=owner.id,
                display_name=owner.display_name or owner.email,
                email=owner.email,
                is_owner=True,
                permissions=ProjectPermissionSet(
                    edit_project=True,
                    manage_papers=True,
                    manage_collaborators=True,
                ),
                joined_at=project.created_at,
            ),
            *[_collaborator_response(item) for item in collaborators],
        ]

    def update_member(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        user_id: int,
        request: ProjectCollaboratorUpdateRequest,
    ) -> ProjectCollaboratorResponse:
        return _collaborator_response(
            project_repository.update_collaborator(
                self._db,
                project_id=project_id,
                actor_id=actor_id,
                target_user_id=user_id,
                requested=request,
            )
        )

    def remove_member(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        user_id: int,
    ) -> None:
        project_repository.remove_collaborator(
            self._db,
            project_id=project_id,
            actor_id=actor_id,
            target_user_id=user_id,
        )

    def leave(self, *, user_id: int, project_id: UUID) -> None:
        project_repository.leave(
            self._db,
            project_id=project_id,
            user_id=user_id,
        )

    def transfer(
        self,
        *,
        owner_id: int,
        project_id: UUID,
        request: ProjectTransferRequest,
    ) -> ProjectResponse:
        project = project_repository.transfer(
            self._db,
            project_id=project_id,
            owner_id=owner_id,
            new_owner_id=request.new_owner_id,
        )
        return self._project(project, user_id=owner_id)

    def accept_invitation(
        self,
        *,
        raw_token: str,
        user_id: int,
        email: str,
    ) -> None:
        project_repository.accept_invitation_token(
            self._db,
            raw_token=raw_token,
            user_id=user_id,
            email=email,
        )

    def list_invitations(
        self,
        *,
        actor_id: int,
        project_id: UUID,
    ) -> list[ProjectInvitationResponse]:
        return [
            self._invitation(invitation.id)
            for invitation in project_repository.list_project_invitations(
                self._db,
                project_id=project_id,
                actor_id=actor_id,
            )
        ]

    def create_invitation(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        request: ProjectInvitationCreateRequest,
    ) -> InvitationDelivery:
        return self._delivery(
            project_repository.create_invitation(
                self._db,
                project_id=project_id,
                actor_id=actor_id,
                email=str(request.email),
                requested=request,
            )
        )

    def resend_invitation(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        invitation_id: UUID,
    ) -> InvitationDelivery:
        return self._delivery(
            project_repository.resend_invitation(
                self._db,
                project_id=project_id,
                invitation_id=invitation_id,
                actor_id=actor_id,
            )
        )

    def revoke_invitation(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        invitation_id: UUID,
    ) -> None:
        project_repository.revoke_invitation(
            self._db,
            project_id=project_id,
            invitation_id=invitation_id,
            actor_id=actor_id,
        )

    def collect_document(
        self,
        *,
        actor: Actor,
        request: CollectPaperFromProjectRequest,
    ) -> UUID | None:
        document = project_document_repository.add_project_paper_to_library(
            self._db,
            document_id=request.document_id,
            project_id=request.source_project_id,
            current_user=actor,
        )
        return document.id if document is not None else None

    def add_documents(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        request: AddPaperToProjectRequest,
    ) -> tuple[int, int]:
        associations, existing_count = (
            project_document_repository.attach_library_documents(
                self._db,
                document_ids=request.document_ids,
                user=actor,
                project_id=project_id,
            )
        )
        return len(associations), existing_count

    def list_documents(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        load_urls: bool,
    ) -> ProjectPaperListResponse:
        papers = project_document_repository.get_papers_metadata_by_project_id(
            self._db,
            project_id=project_id,
            user=actor,
        )
        library_document_ids = set(
            project_document_repository.get_library_document_ids(
                self._db,
                document_ids=[paper.id for paper in papers],
                user=actor,
            )
        )
        file_urls = (
            s3_service.generate_presigned_urls(
                {str(paper.id): paper.s3_object_key for paper in papers}
            )
            if load_urls
            else {}
        )
        return ProjectPaperListResponse(
            items=[
                ProjectPaperSummaryResponse(
                    document_id=paper.id,
                    title=paper.title,
                    created_at=paper.created_at,
                    abstract=paper.abstract,
                    authors=paper.authors,
                    institutions=paper.institutions,
                    status="reading",
                    journal=paper.journal,
                    publisher=paper.publisher,
                    doi=paper.doi,
                    publish_date=paper.publish_date,
                    file_url=file_urls.get(str(paper.id)),
                    in_library=paper.id in library_document_ids,
                )
                for paper in papers
            ]
        )

    def pending_uploads(
        self,
        *,
        actor: Actor,
        project_id: UUID,
    ) -> ProjectPendingUploadsResponse:
        jobs = upload_reservation_repository.get_in_progress_jobs_for_project(
            self._db,
            project_id=project_id,
            user=actor,
        )
        return ProjectPendingUploadsResponse(
            items=[
                ProjectPendingUploadResponse(
                    job_id=job.id,
                    status=job.job.status,
                    document_id=document.id,
                    title=document.title,
                    started_at=job.job.started_at,
                )
                for job, document in jobs
            ]
        )

    def document_storage_key(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        document_id: UUID,
    ) -> str | None:
        document = project_document_repository.get_paper_by_project(
            self._db,
            document_id=document_id,
            project_id=project_id,
            user=actor,
        )
        return document.s3_object_key if document is not None else None

    def projects_for_document(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> list[ProjectResponse]:
        return [
            self._project(project, user_id=actor.id)
            for project in project_document_repository.get_projects_by_document_id(
                self._db,
                document_id=document_id,
                user=actor,
            )
        ]

    def remove_document(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        document_id: UUID,
    ) -> None:
        project_document_repository.remove_by_paper_and_project(
            self._db,
            document_id=document_id,
            project_id=project_id,
            user=actor,
        )
class PostHogProjectEvents:
    def __init__(self, db: Session) -> None:
        self._db = db

    def record(
        self,
        *,
        actor: Actor,
        name: str,
        properties: dict[str, object] | None = None,
    ) -> None:
        track_event(
            name,
            user_id=str(actor.id),
            properties=properties,
            db=self._db,
        )


class EmailProjectInvitationNotifier:
    def send(self, *, inviter: Actor, delivery: InvitationDelivery) -> None:
        send_project_invite_email(
            to_email=delivery.recipient_email,
            from_name=str(inviter.display_name or inviter.email),
            project_title=delivery.project_title,
            invitation_token=delivery.raw_token,
        )
