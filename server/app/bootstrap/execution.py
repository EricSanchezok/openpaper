"""Application executor construction and HTTP dependency."""

from __future__ import annotations

from typing import cast

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.settings import AppSettings
from app.database.database import SessionLocal
from app.modules.conversations.application.chat import ConversationChat
from app.modules.identity.application.onboarding import FinishOnboarding
from app.modules.billing.application.webhooks import ProcessStripeWebhook
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.bootstrap.workflows.research_generation import ResearchGenerationWorkflow
from app.bootstrap.workflows.zotero import ZoteroWorkflow
from app.shared.application import ApplicationExecutor
from app.shared.infrastructure import SqlAlchemyApplicationExecutor
from fastapi import Request


def create_application_executor(
    settings: AppSettings,
) -> ApplicationExecutor[ApplicationCapabilities]:
    return SqlAlchemyApplicationExecutor(
        SessionLocal,
        lambda session: ApplicationCapabilities(session, settings),
    )


def create_conversation_chat(
    executor: ApplicationExecutor[ApplicationCapabilities],
) -> ConversationChat:
    from app.bootstrap.adapters.conversation_chat import (
        DefaultConversationChatGateway,
    )

    return ConversationChat(DefaultConversationChatGateway(executor))


def create_onboarding_finisher() -> FinishOnboarding:
    from app.bootstrap.container import build_finish_onboarding

    return build_finish_onboarding()


def create_stripe_webhook_processor() -> ProcessStripeWebhook:
    from app.bootstrap.adapters.stripe_webhook_adapter import StripeWebhookAdapter

    return ProcessStripeWebhook(StripeWebhookAdapter(SessionLocal))


def create_paper_ingestion_workflow(
    executor: ApplicationExecutor[ApplicationCapabilities],
) -> PaperIngestionWorkflow:
    from app.bootstrap.container import build_pdf_url_source

    return PaperIngestionWorkflow(
        executor=executor,
        url_source=build_pdf_url_source(),
    )


def create_research_generation_workflow(
    executor: ApplicationExecutor[ApplicationCapabilities],
) -> ResearchGenerationWorkflow:
    from app.bootstrap.container import build_generation_capacity

    return ResearchGenerationWorkflow(
        executor=executor,
        capacity=build_generation_capacity(),
    )


def create_zotero_workflow(
    executor: ApplicationExecutor[ApplicationCapabilities],
) -> ZoteroWorkflow:
    from app.bootstrap.adapters.zotero_operations import DefaultZoteroOperations

    return ZoteroWorkflow(
        executor=executor,
        operations=DefaultZoteroOperations(SessionLocal),
    )


def get_application_executor(
    request: Request,
) -> ApplicationExecutor[ApplicationCapabilities]:
    return cast(
        ApplicationExecutor[ApplicationCapabilities],
        request.app.state.application_executor,
    )


def get_conversation_chat(request: Request) -> ConversationChat:
    return cast(ConversationChat, request.app.state.conversation_chat)


def get_onboarding_finisher(request: Request) -> FinishOnboarding:
    return cast(FinishOnboarding, request.app.state.onboarding_finisher)


def get_stripe_webhook_processor(request: Request) -> ProcessStripeWebhook:
    return cast(ProcessStripeWebhook, request.app.state.stripe_webhook_processor)


def get_paper_ingestion_workflow(request: Request) -> PaperIngestionWorkflow:
    return cast(PaperIngestionWorkflow, request.app.state.paper_ingestion_workflow)


def get_research_generation_workflow(
    request: Request,
) -> ResearchGenerationWorkflow:
    return cast(
        ResearchGenerationWorkflow,
        request.app.state.research_generation_workflow,
    )


def get_zotero_workflow(request: Request) -> ZoteroWorkflow:
    return cast(ZoteroWorkflow, request.app.state.zotero_workflow)
