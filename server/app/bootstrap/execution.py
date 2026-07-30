"""Application executor construction and HTTP dependency."""

from __future__ import annotations

import asyncio
from typing import cast
from urllib.parse import urlsplit

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.settings import AppSettings
from app.llm.conversation_agent import ConversationAgentRuntime
from app.database.database import SessionLocal
from app.modules.access_keys.application.contracts import AuthenticatedAccessKey
from app.modules.conversations.application.chat import ConversationChat
from app.modules.identity.application.onboarding import FinishOnboarding
from app.modules.billing.application.webhooks import ProcessStripeWebhook
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.bootstrap.workflows.research_generation import ResearchGenerationWorkflow
from app.bootstrap.workflows.zotero import ZoteroWorkflow
from app.bootstrap.adapters.job_completion_processor import JobCompletionProcessor
from app.shared.application import ApplicationExecutor
from app.shared.infrastructure import SqlAlchemyApplicationExecutor
from app.tooling import ToolCatalog, ToolDispatcher
from app.transport.mcp.server import (
    AuthenticatedMcpApplication,
    build_mcp_transport,
)
from fastapi import Request
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings


def create_application_executor(
    settings: AppSettings,
) -> ApplicationExecutor[ApplicationCapabilities]:
    return SqlAlchemyApplicationExecutor(
        SessionLocal,
        lambda session: ApplicationCapabilities(session, settings),
    )


def create_conversation_chat(
    executor: ApplicationExecutor[ApplicationCapabilities],
    runtime: ConversationAgentRuntime,
) -> ConversationChat:
    from app.bootstrap.adapters.conversation_chat import (
        DefaultConversationChatGateway,
    )

    return ConversationChat(DefaultConversationChatGateway(executor, runtime))


def create_workspace_tooling(
    *,
    executor: ApplicationExecutor[ApplicationCapabilities],
    ingestion: PaperIngestionWorkflow,
) -> tuple[
    ToolCatalog[ApplicationCapabilities],
    ToolDispatcher[ApplicationCapabilities],
]:
    from app.tooling.workspace import build_workspace_tool_catalog

    catalog = build_workspace_tool_catalog(ingestion=ingestion)
    return catalog, ToolDispatcher(catalog=catalog, executor=executor)


def create_conversation_agent_runtime(
    *,
    catalog: ToolCatalog[ApplicationCapabilities],
    dispatcher: ToolDispatcher[ApplicationCapabilities],
) -> ConversationAgentRuntime:
    return ConversationAgentRuntime(catalog=catalog, dispatcher=dispatcher)


def create_mcp_transport(
    *,
    settings: AppSettings,
    catalog: ToolCatalog[ApplicationCapabilities],
    dispatcher: ToolDispatcher[ApplicationCapabilities],
    executor: ApplicationExecutor[ApplicationCapabilities],
) -> tuple[StreamableHTTPSessionManager, AuthenticatedMcpApplication]:
    async def authenticate(token: str) -> AuthenticatedAccessKey:
        return await asyncio.to_thread(
            executor.command,
            lambda capabilities: capabilities.access_keys.authenticate(token),
        )

    public_url = urlsplit(settings.client_domain)
    public_host = public_url.netloc
    allowed_hosts = [public_host]
    allowed_origins = [settings.client_domain.rstrip("/")]
    if settings.environment.casefold() != "production":
        allowed_hosts.extend(["localhost:*", "127.0.0.1:*", "testserver"])
        allowed_origins.extend(["http://localhost:*", "http://127.0.0.1:*"])
    return build_mcp_transport(
        catalog=catalog,
        dispatcher=dispatcher,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        ),
        authenticate=authenticate,
    )


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


def create_job_completion_processor() -> JobCompletionProcessor:
    return JobCompletionProcessor(SessionLocal)


def get_application_executor(
    request: Request,
) -> ApplicationExecutor[ApplicationCapabilities]:
    return cast(
        ApplicationExecutor[ApplicationCapabilities],
        request.app.state.application_executor,
    )


def get_conversation_chat(request: Request) -> ConversationChat:
    return cast(ConversationChat, request.app.state.conversation_chat)


def get_tool_catalog(
    request: Request,
) -> ToolCatalog[ApplicationCapabilities]:
    return cast(
        ToolCatalog[ApplicationCapabilities],
        request.app.state.tool_catalog,
    )


def get_tool_dispatcher(
    request: Request,
) -> ToolDispatcher[ApplicationCapabilities]:
    return cast(
        ToolDispatcher[ApplicationCapabilities],
        request.app.state.tool_dispatcher,
    )


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


def get_job_completion_processor(request: Request) -> JobCompletionProcessor:
    return cast(
        JobCompletionProcessor,
        request.app.state.job_completion_processor,
    )
