"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import { useToast } from "@/components/ui/toast";
import { useAuthSession, type Actor } from "@/features/authentication";
import { AppShell } from "./components/app-shell";
import { ConversationView } from "./components/conversation-view";
import {
  createLiveTurn,
  reduceLiveTurn,
  type LiveTurn,
} from "./conversation-state";
import { HomeDashboard } from "./components/home-dashboard";
import { useDesktopLayout } from "./hooks/use-desktop-layout";
import {
  createConversation,
  streamConversationMessage,
  updateConversationContext,
  type ConversationStreamEvent,
} from "./api/conversations";
import { homeKeys } from "./api/keys";
import { homeQueries } from "./api/queries";
import {
  ResearchComposer,
  useResearchComposerForm,
  type ReasoningLevel,
  type ResearchContext,
} from "./components/research-composer";

function sameContext(left: ResearchContext, right: ResearchContext) {
  if (left.kind !== right.kind) return false;
  if (left.kind === "library" || right.kind === "library") return true;
  return (
    [...(left.project_ids ?? [])].sort().join(",") ===
      [...(right.project_ids ?? [])].sort().join(",") &&
    [...(left.document_ids ?? [])].sort().join(",") ===
      [...(right.document_ids ?? [])].sort().join(",")
  );
}

export function HomeWorkspace({
  actor,
  initialConversationId,
}: {
  actor: Actor;
  initialConversationId?: string;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const toast = useToast();
  const t = useTranslations("Home");
  const locale = useLocale() === "zh-CN" ? "zh-CN" : "en";
  const { signOut } = useAuthSession();
  const [pendingConversationId, setPendingConversationId] =
    React.useState<string>();
  const [collapsed, setCollapsed] = React.useState(false);
  const [signingOut, setSigningOut] = React.useState(false);
  const [contextOverrides, setContextOverrides] = React.useState<
    Record<string, ResearchContext>
  >({});
  const [reasoningLevel, setReasoningLevel] =
    React.useState<ReasoningLevel>("standard");
  const [liveTurn, setLiveTurn] = React.useState<LiveTurn | null>(null);
  const [liveTurnConversationId, setLiveTurnConversationId] =
    React.useState<string>();
  const streamController = React.useRef<AbortController | null>(null);
  const composerForm = useResearchComposerForm();
  const isDesktop = useDesktopLayout();

  const activeConversationId = initialConversationId ?? pendingConversationId;

  const conversationsQuery = useQuery(homeQueries.conversations());
  const papersQuery = useQuery(homeQueries.papers());
  const projectsQuery = useQuery(homeQueries.projects());
  const conversationQuery = useQuery({
    ...homeQueries.conversation(activeConversationId ?? ""),
    enabled: Boolean(activeConversationId),
  });
  const messagesQuery = useQuery({
    ...homeQueries.messages(activeConversationId ?? ""),
    enabled: Boolean(activeConversationId),
  });

  React.useEffect(() => () => streamController.current?.abort(), []);

  const conversations = conversationsQuery.data?.items ?? [];
  const papers = papersQuery.data?.items ?? [];
  const projects = projectsQuery.data?.items ?? [];
  const contextKey = activeConversationId ?? "new";
  const context =
    contextOverrides[contextKey] ??
    conversationQuery.data?.paper_context ??
    ({ kind: "library" } satisfies ResearchContext);

  function handleContextChange(nextContext: ResearchContext) {
    setContextOverrides((current) => ({
      ...current,
      [contextKey]: nextContext,
    }));
  }

  function applyStreamEvent(event: ConversationStreamEvent) {
    setLiveTurn((current) => reduceLiveTurn(current, event));
  }

  async function sendMessage(message: string) {
    if (streamController.current) return;
    let conversationId = activeConversationId;
    try {
      if (!conversationId) {
        const conversation = await createConversation({
          scope_type: "global",
          paper_context: context,
        });
        conversationId = conversation.id;
        setPendingConversationId(conversation.id);
        setContextOverrides((current) => ({
          ...current,
          [conversation.id]: context,
        }));
        queryClient.setQueryData(
          homeKeys.conversation(conversation.id),
          conversation,
        );
        router.replace(`/?conversation=${conversation.id}`, { scroll: false });
      } else if (
        conversationQuery.data &&
        !sameContext(context, conversationQuery.data.paper_context)
      ) {
        await updateConversationContext(conversationId, context);
      }

      const controller = new AbortController();
      const turnId = crypto.randomUUID();
      streamController.current = controller;
      setLiveTurnConversationId(conversationId);
      setLiveTurn(createLiveTurn(turnId, message));
      let failed = false;
      await streamConversationMessage({
        conversationId,
        message: {
          turn_id: turnId,
          user_query: message,
          locale,
          time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
          reasoning_level: reasoningLevel,
        },
        signal: controller.signal,
        onEvent: (event) => {
          if (event.type === "error") failed = true;
          applyStreamEvent(event);
        },
      });

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: homeKeys.conversations() }),
        queryClient.invalidateQueries({
          queryKey: homeKeys.messages(conversationId),
        }),
        queryClient.invalidateQueries({
          queryKey: homeKeys.conversation(conversationId),
        }),
      ]);
      if (!failed) setLiveTurn(null);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        setLiveTurn((current) =>
          current ? { ...current, state: "cancelled" } : current,
        );
        if (conversationId) {
          await Promise.all([
            queryClient.invalidateQueries({
              queryKey: homeKeys.messages(conversationId),
            }),
            queryClient.invalidateQueries({
              queryKey: homeKeys.conversation(conversationId),
            }),
          ]);
        }
      } else if (activeConversationId || conversationId) {
        setLiveTurn((current) =>
          current ? { ...current, state: "error" } : current,
        );
      } else {
        toast.notify({
          title: t("conversation.error"),
          description: t("conversation.retryHint"),
        });
      }
    } finally {
      streamController.current = null;
      setPendingConversationId(undefined);
    }
  }

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await signOut();
      router.replace("/login");
    } finally {
      setSigningOut(false);
    }
  }

  const conversationBusy = liveTurn?.state === "streaming";
  const conversationUnavailable =
    conversationQuery.isPending ||
    conversationQuery.isError ||
    messagesQuery.isError ||
    conversationQuery.data?.capabilities.send !== true;
  const mobileComposer = !isDesktop ? (
    <ResearchComposer
      busy={activeConversationId ? conversationBusy : undefined}
      compact={Boolean(activeConversationId)}
      context={context}
      form={composerForm}
      onContextChange={handleContextChange}
      onReasoningLevelChange={setReasoningLevel}
      onStop={
        activeConversationId
          ? () => streamController.current?.abort()
          : undefined
      }
      onSubmit={sendMessage}
      papers={papers}
      projects={projects}
      reasoningLevel={reasoningLevel}
      unavailable={activeConversationId ? conversationUnavailable : undefined}
    />
  ) : undefined;

  return (
    <AppShell
      activeConversationId={activeConversationId}
      actor={actor}
      collapsed={collapsed}
      conversations={conversations}
      onCollapsedChange={setCollapsed}
      onReasoningLevelChange={setReasoningLevel}
      onSignOut={handleSignOut}
      reasoningLevel={reasoningLevel}
      signingOut={signingOut}
      mobileComposer={mobileComposer}
    >
      {activeConversationId ? (
        <ConversationView
          canSend={conversationQuery.data?.capabilities.send === true}
          composerForm={composerForm}
          context={context}
          error={conversationQuery.isError || messagesQuery.isError}
          liveTurn={
            liveTurnConversationId === activeConversationId ? liveTurn : null
          }
          loading={conversationQuery.isPending || messagesQuery.isPending}
          messages={messagesQuery.data?.items ?? []}
          onContextChange={handleContextChange}
          onReasoningLevelChange={setReasoningLevel}
          onRetry={() => {
            void conversationQuery.refetch();
            void messagesQuery.refetch();
          }}
          onStop={() => streamController.current?.abort()}
          onSubmit={sendMessage}
          papers={papers}
          projects={projects}
          reasoningLevel={reasoningLevel}
          readOnlyReason={conversationQuery.data?.read_only_reason}
          showComposer={isDesktop}
          title={conversationQuery.data?.title}
        />
      ) : (
        <HomeDashboard
          composerForm={composerForm}
          context={context}
          onContextChange={handleContextChange}
          onReasoningLevelChange={setReasoningLevel}
          onRetryPapers={() => void papersQuery.refetch()}
          onRetryProjects={() => void projectsQuery.refetch()}
          onSubmit={sendMessage}
          papers={papers}
          papersError={papersQuery.isError}
          papersLoading={papersQuery.isPending}
          projects={projects}
          projectsError={projectsQuery.isError}
          projectsLoading={projectsQuery.isPending}
          reasoningLevel={reasoningLevel}
          showComposer={isDesktop}
        />
      )}
    </AppShell>
  );
}

export function HomePage({ conversationId }: { conversationId?: string }) {
  const router = useRouter();
  const t = useTranslations("Home.session");
  const session = useAuthSession();

  React.useEffect(() => {
    if (session.status === "anonymous") {
      const returnTo = conversationId
        ? `/?conversation=${encodeURIComponent(conversationId)}`
        : "/";
      router.replace(`/login?returnTo=${encodeURIComponent(returnTo)}`);
    }
  }, [conversationId, router, session.status]);

  if (session.status === "bootstrapping" || session.status === "anonymous") {
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <div className="w-full max-w-sm">
          <LoadingState label={t("checking")} />
        </div>
      </main>
    );
  }
  if (session.status === "unavailable") {
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <AsyncFeedback
          action={{ label: t("retry"), onClick: session.retryBootstrap }}
          description={t("unavailableDescription")}
          state="offline"
          title={t("unavailableTitle")}
        />
      </main>
    );
  }
  if (!session.actor) return null;
  return (
    <HomeWorkspace
      actor={session.actor}
      initialConversationId={conversationId}
    />
  );
}
