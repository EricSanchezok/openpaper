from app.database.admin_auth import build_admin_authentication_backend
from app.database.database import engine
from app.database.models import (
    Annotation,
    Conversation,
    DataTableExtractionJob,
    DataTableExtractionResult,
    DataTableRow,
    Highlight,
    Message,
    Onboarding,
    Document,
    PaperNote,
    Project,
    ProjectCollaborator,
    ProjectInvitation,
    ProjectPaper,
    Subscription,
    AuthUser,
    UserProfile,
    ZoteroConnection,
    ZoteroImportedItem,
    ZoteroOAuthPending,
)
from fastapi import FastAPI
from sqladmin import Admin, ModelView


class AuthUserAdmin(ModelView, model=AuthUser):
    name = "Cloud Auth User"
    name_plural = "Cloud Auth Users"
    column_list = [
        AuthUser.id,
        AuthUser.email,
        AuthUser.display_name,
        AuthUser.status,
        AuthUser.email_verified_at,
        AuthUser.created_at,
    ]
    column_searchable_list = [AuthUser.email, AuthUser.display_name]
    can_create = False
    can_edit = False
    can_delete = False


class UserProfileAdmin(ModelView, model=UserProfile):
    name = "Scholens User Profile"
    name_plural = "Scholens User Profiles"
    column_list = [
        UserProfile.user_id,
        UserProfile.locale,
        UserProfile.is_admin,
        UserProfile.is_blocked,
        UserProfile.created_at,
    ]
    column_searchable_list = [UserProfile.user_id, UserProfile.locale]
    can_create = False
    can_delete = False


class OnboardingAdmin(ModelView, model=Onboarding):
    column_list = [
        Onboarding.id,
        Onboarding.user_id,
    ]
    column_searchable_list = [
        Onboarding.user_id,
        Onboarding.research_fields,
        Onboarding.job_titles,
    ]


class SubscriptionAdmin(ModelView, model=Subscription):
    column_list = [
        Subscription.id,
        Subscription.user_id,
        Subscription.plan,
        Subscription.status,
        Subscription.created_at,
        Subscription.cancel_at_period_end,
    ]
    column_searchable_list = [
        Subscription.user_id,
        Subscription.plan,
        Subscription.status,
    ]


class ProjectAdmin(ModelView, model=Project):
    column_list = [
        Project.id,
        Project.title,
        Project.description,
    ]

    column_searchable_list = [Project.title]


class ProjectCollaboratorAdmin(ModelView, model=ProjectCollaborator):
    column_list = [
        ProjectCollaborator.id,
        "project",
        "user",
        ProjectCollaborator.can_edit_project,
        ProjectCollaborator.can_manage_papers,
        ProjectCollaborator.can_manage_collaborators,
    ]
    column_searchable_list = [
        ProjectCollaborator.project_id,
        ProjectCollaborator.user_id,
    ]
    column_details_list = [
        ProjectCollaborator.id,
        "project",
        "user",
        ProjectCollaborator.can_edit_project,
        ProjectCollaborator.can_manage_papers,
        ProjectCollaborator.can_manage_collaborators,
    ]


class ProjectPaperAdmin(ModelView, model=ProjectPaper):
    column_list = [
        ProjectPaper.id,
        ProjectPaper.project_id,
        ProjectPaper.document_id,
    ]
    column_searchable_list = [ProjectPaper.project_id, ProjectPaper.document_id]


class HighlightAdmin(ModelView, model=Highlight):
    column_list = [
        Highlight.id,
        Highlight.user_id,
        Highlight.paper_id,
        Highlight.raw_text,
    ]
    column_searchable_list = [Highlight.raw_text]


class PaperAdmin(ModelView, model=Document):
    column_list = [Document.id, Document.title, Document.created_by_id]
    column_searchable_list = [Document.title]


class AnnotationAdmin(ModelView, model=Annotation):
    column_list = [
        Annotation.id,
        Annotation.user_id,
        Annotation.paper_id,
        Annotation.content,
    ]
    column_searchable_list = [Annotation.content]


class PaperNoteAdmin(ModelView, model=PaperNote):
    column_list = [
        PaperNote.id,
        PaperNote.user_id,
        PaperNote.paper_id,
        PaperNote.content,
    ]
    column_searchable_list = [PaperNote.content]


class ConversationAdmin(ModelView, model=Conversation):
    column_list = [
        Conversation.id,
        Conversation.user_id,
        Conversation.conversable_id,
        Conversation.title,
    ]
    column_searchable_list = [Conversation.title]


class MessageAdmin(ModelView, model=Message):
    column_list = [
        Message.id,
        Message.user_id,
        Message.conversation_id,
        Message.content,
        Message.role,
    ]
    column_searchable_list = [Message.content]


class DataTableExtractionJobAdmin(ModelView, model=DataTableExtractionJob):
    column_list = [
        DataTableExtractionJob.id,
        DataTableExtractionJob.project_id,
        DataTableExtractionJob.status,
        DataTableExtractionJob.created_at,
    ]
    column_searchable_list = [
        DataTableExtractionJob.project_id,
        DataTableExtractionJob.status,
    ]


class DataTableExtractionResultAdmin(ModelView, model=DataTableExtractionResult):
    column_list = [
        DataTableExtractionResult.id,
        DataTableExtractionResult.success,
        DataTableExtractionResult.created_at,
    ]
    column_searchable_list = [
        DataTableExtractionResult.success,
    ]


class DataTableRowAdmin(ModelView, model=DataTableRow):
    column_list = [
        DataTableRow.id,
        DataTableRow.data_table_id,
        DataTableRow.paper_id,
        DataTableRow.values,
        DataTableRow.created_at,
    ]
    column_searchable_list = [
        DataTableRow.data_table_id,
        DataTableRow.paper_id,
    ]


class ProjectInvitationAdmin(ModelView, model=ProjectInvitation):
    column_list = [
        ProjectInvitation.id,
        ProjectInvitation.project_id,
        ProjectInvitation.email,
        ProjectInvitation.expires_at,
        ProjectInvitation.created_at,
    ]
    column_searchable_list = [
        ProjectInvitation.project_id,
        ProjectInvitation.email,
    ]


class ZoteroConnectionAdmin(ModelView, model=ZoteroConnection):
    name = "Zotero Connection"
    name_plural = "Zotero Connections"
    icon = "fa-solid fa-plug"
    # api_key is intentionally omitted to avoid exposing the secret.
    column_list = [
        ZoteroConnection.id,
        ZoteroConnection.user_id,
        ZoteroConnection.zotero_user_id,
    ]
    column_searchable_list = [
        ZoteroConnection.user_id,
        ZoteroConnection.zotero_user_id,
    ]


class ZoteroImportedItemAdmin(ModelView, model=ZoteroImportedItem):
    name = "Zotero Imported Item"
    name_plural = "Zotero Imported Items"
    icon = "fa-solid fa-file-import"
    column_list = [
        ZoteroImportedItem.id,
        ZoteroImportedItem.user_id,
        ZoteroImportedItem.zotero_item_key,
        ZoteroImportedItem.status,
        ZoteroImportedItem.paper_id,
        ZoteroImportedItem.error_message,
        ZoteroImportedItem.last_synced_at,
    ]
    column_searchable_list = [
        ZoteroImportedItem.user_id,
        ZoteroImportedItem.zotero_item_key,
        ZoteroImportedItem.status,
        ZoteroImportedItem.paper_id,
    ]
    column_sortable_list = [
        ZoteroImportedItem.status,
        ZoteroImportedItem.last_synced_at,
    ]
    column_default_sort = [(ZoteroImportedItem.last_synced_at, True)]
    column_details_list = [
        ZoteroImportedItem.id,
        ZoteroImportedItem.user_id,
        ZoteroImportedItem.zotero_item_key,
        ZoteroImportedItem.zotero_attachment_key,
        ZoteroImportedItem.import_source,
        ZoteroImportedItem.source_url,
        ZoteroImportedItem.paper_id,
        ZoteroImportedItem.upload_job_id,
        ZoteroImportedItem.status,
        ZoteroImportedItem.annotations_payload,
        ZoteroImportedItem.error_message,
        ZoteroImportedItem.last_synced_at,
    ]


class ZoteroOAuthPendingAdmin(ModelView, model=ZoteroOAuthPending):
    name = "Zotero OAuth Pending"
    name_plural = "Zotero OAuth Pending"
    icon = "fa-solid fa-hourglass-half"
    # oauth_token_secret is intentionally omitted to avoid exposing the secret.
    column_list = [
        ZoteroOAuthPending.id,
        ZoteroOAuthPending.user_id,
        ZoteroOAuthPending.expires_at,
    ]
    column_searchable_list = [
        ZoteroOAuthPending.user_id,
    ]
    column_sortable_list = [
        ZoteroOAuthPending.expires_at,
    ]


def setup_admin(app: FastAPI) -> None:
    admin = Admin(
        app,
        engine,
        authentication_backend=build_admin_authentication_backend(),
    )

    admin.add_view(AuthUserAdmin)
    admin.add_view(UserProfileAdmin)
    admin.add_view(OnboardingAdmin)
    admin.add_view(PaperAdmin)
    admin.add_view(HighlightAdmin)
    admin.add_view(AnnotationAdmin)
    admin.add_view(PaperNoteAdmin)
    admin.add_view(ConversationAdmin)
    admin.add_view(MessageAdmin)
    admin.add_view(ProjectAdmin)
    admin.add_view(ProjectInvitationAdmin)
    admin.add_view(ProjectCollaboratorAdmin)
    admin.add_view(ProjectPaperAdmin)
    admin.add_view(SubscriptionAdmin)
    admin.add_view(DataTableExtractionJobAdmin)
    admin.add_view(DataTableExtractionResultAdmin)
    admin.add_view(DataTableRowAdmin)
    admin.add_view(ZoteroConnectionAdmin)
    admin.add_view(ZoteroImportedItemAdmin)
    admin.add_view(ZoteroOAuthPendingAdmin)
