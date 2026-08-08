"use client";

import {
  CheckCircle,
  NavArrowDown,
  Page,
  WarningTriangle,
} from "iconoir-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import type { components } from "@/lib/api/generated/schema";
import { cn } from "@/lib/utilities/cn";
import type {
  ConversationActivity,
  ConversationFailure,
  LiveTurn,
} from "../conversation-state";
import type { ComposerValues } from "../schemas";
import type { UseFormReturn } from "react-hook-form";
import {
  ResearchComposer,
  type ReasoningLevel,
  type ResearchContext,
} from "./research-composer";
import { MessageContent } from "./message-content";

type Message =
  components["schemas"]["app__modules__conversations__application__contracts__conversations__MessageResponse"];
type LibraryPaper = components["schemas"]["LibraryPaperResponse"];
type Project = components["schemas"]["ProjectResponse"];
type ReferenceBundle = components["schemas"]["ReferenceBundle"];

function isReferenceBundle(value: unknown): value is ReferenceBundle {
  return Boolean(
    value &&
    typeof value === "object" &&
    Array.isArray((value as { sources?: unknown }).sources),
  );
}

function sourceCount(references: unknown) {
  return isReferenceBundle(references) ? (references.sources?.length ?? 0) : 0;
}

function activityLabel(
  activity: ConversationActivity,
  t: ReturnType<typeof useTranslations<"Home.conversation">>,
) {
  if (activity.category === "connector") {
    return t("activity.connector", {
      connector: activity.connector_name || t("activity.connectorFallback"),
    });
  }
  return t(`activity.${activity.category}`);
}

function activitySummary(
  activities: ConversationActivity[],
  contentStarted: boolean,
  state: LiveTurn["state"],
  sources: number,
  failure: ConversationFailure | null,
  t: ReturnType<typeof useTranslations<"Home.conversation">>,
) {
  if (state === "cancelled") return t("activity.stopped");
  if (state === "error") {
    if (failure?.code?.endsWith("_unavailable")) {
      return t("failure.unavailable");
    }
    if (failure?.kind === "rate_limited") return t("failure.rateLimited");
    return t("failure.generic");
  }
  const running = activities.findLast(
    (activity) => activity.state === "running",
  );
  if (state === "streaming") {
    if (running?.category === "search") return t("activity.searching");
    if (running?.category === "read") return t("activity.reading");
    if (running?.category === "workspace_action") {
      return t("activity.updatingWorkspace");
    }
    if (running?.category === "connector") {
      return t("activity.usingConnector", {
        connector: running.connector_name || t("activity.connectorFallback"),
      });
    }
    if (!contentStarted || activities.length === 0) {
      return t("activity.thinking");
    }
  }
  const failed = activities.filter(
    (activity) => activity.state === "failed",
  ).length;
  return t(
    failed > 0 ? "activity.partialSummary" : "activity.completeSummary",
    {
      count: activities.length,
      sources,
    },
  );
}

function ActivityDisclosure({
  activities,
  contentStarted,
  sourceTotal,
  state,
  failure,
  onOpenChange,
}: {
  activities: ConversationActivity[];
  contentStarted: boolean;
  sourceTotal: number;
  state: LiveTurn["state"];
  failure: ConversationFailure | null;
  onOpenChange?: (open: boolean) => void;
}) {
  const t = useTranslations("Home.conversation");
  const [openState, setOpenState] = React.useState({
    contentStarted,
    open: false,
  });
  const open =
    openState.contentStarted === contentStarted ? openState.open : false;
  const hasHistory = activities.length > 0;
  const visible =
    hasHistory ||
    state === "cancelled" ||
    state === "error" ||
    (state === "streaming" && !contentStarted);
  const summary = activitySummary(
    activities,
    contentStarted,
    state,
    sourceTotal,
    failure,
    t,
  );

  if (!visible) return null;

  function toggle() {
    if (!hasHistory) return;
    onOpenChange?.(!open);
    setOpenState({ contentStarted, open: !open });
  }

  return (
    <div className="text-secondary text-base lg:text-sm" data-state={state}>
      {hasHistory ? (
        <button
          aria-expanded={open}
          className="hover:text-foreground focus-visible:text-foreground flex min-h-11 w-full items-center gap-2 rounded-[var(--radius-sm)] text-left transition-colors motion-reduce:transition-none lg:min-h-8"
          onClick={toggle}
          type="button"
        >
          <span
            aria-live="polite"
            className="activity-copy-enter min-w-0 flex-1 truncate"
            key={summary}
          >
            {summary}
          </span>
          <Icon
            className={cn(
              "shrink-0 transition-transform duration-150 motion-reduce:transition-none",
              open && "rotate-180",
            )}
            glyph={NavArrowDown}
            size={16}
            tone="secondary"
          />
        </button>
      ) : (
        <p
          aria-live="polite"
          className="flex min-h-11 items-center lg:min-h-8"
          role="status"
        >
          <span className="activity-copy-enter" key={summary}>
            {summary}
          </span>
        </p>
      )}
      {open && hasHistory && (
        <ol className="border-line mt-1 grid gap-2 border-t pt-3 pb-1">
          {activities.map((activity) => (
            <li className="flex min-w-0 gap-2.5" key={activity.id}>
              <Icon
                className="mt-0.5 shrink-0"
                glyph={
                  activity.state === "failed"
                    ? WarningTriangle
                    : activity.state === "succeeded"
                      ? CheckCircle
                      : Page
                }
                size={16}
                tone="secondary"
              />
              <span className="min-w-0 flex-1">
                <span className="text-foreground block text-sm font-medium lg:text-xs">
                  {activityLabel(activity, t)}
                </span>
                {activity.subject && (
                  <span className="text-muted mt-0.5 block text-sm leading-5 break-words lg:text-xs">
                    {activity.subject}
                  </span>
                )}
                {Boolean(activity.source_count || activity.artifact_count) && (
                  <span className="text-muted mt-0.5 block text-sm lg:text-xs">
                    {t("activity.results", {
                      sources: activity.source_count ?? 0,
                      artifacts: activity.artifact_count ?? 0,
                    })}
                  </span>
                )}
              </span>
              <span className="sr-only">
                {t(`activity.state.${activity.state}`)}
              </span>
            </li>
          ))}
        </ol>
      )}
      {state === "error" && failure?.diagnosticId && (
        <p className="text-muted mt-1 text-xs">
          {t("failure.diagnostic", { id: failure.diagnosticId })}
        </p>
      )}
    </div>
  );
}

function Sources({ references }: { references: unknown }) {
  const t = useTranslations("Home.conversation");
  if (!isReferenceBundle(references) || !references.sources?.length)
    return null;
  const sources = references.sources;
  return (
    <section className="mt-5">
      <div className="lg:text-ui mb-2 flex items-center gap-2 text-base font-medium">
        {t("sources")}
        <span className="text-muted text-xs font-normal">{sources.length}</span>
      </div>
      <div className="grid gap-2">
        {sources.map((source, index) => {
          const title =
            "title" in source && source.title
              ? source.title
              : t("reference", { number: index + 1 });
          const row = (
            <>
              <span className="bg-subtle grid size-6 shrink-0 place-items-center rounded text-xs">
                {index + 1}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium">
                  {title}
                </span>
                <span className="text-caption text-muted mt-0.5 line-clamp-1 block">
                  {source.reference}
                </span>
              </span>
            </>
          );
          return source.kind === "external" ? (
            <a
              className="border-line hover:bg-hover flex min-h-11 items-center gap-2 rounded-[var(--radius-md)] border p-2.5 lg:min-h-0 lg:p-2"
              href={source.url}
              key={`${source.key}-${source.url}`}
              rel="noreferrer"
              target="_blank"
            >
              {row}
            </a>
          ) : (
            <div
              className="border-line flex min-h-11 items-center gap-2 rounded-[var(--radius-md)] border p-2.5 lg:min-h-0 lg:p-2"
              key={`${source.key}-${index}`}
            >
              {row}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function AssistantMessage({
  activities,
  content,
  references,
  sourceTotal,
  state,
  failure,
  onActivityOpenChange,
}: {
  activities: ConversationActivity[];
  content: string;
  references: unknown;
  sourceTotal: number;
  state: LiveTurn["state"];
  failure?: ConversationFailure | null;
  onActivityOpenChange?: (open: boolean) => void;
}) {
  const t = useTranslations("Home.conversation");
  return (
    <article aria-label={t("assistantMessage")} className="grid gap-3">
      <ActivityDisclosure
        activities={activities}
        contentStarted={Boolean(content)}
        onOpenChange={onActivityOpenChange}
        sourceTotal={sourceTotal}
        state={state}
        failure={failure ?? null}
      />
      {content && <MessageContent content={content} />}
      <Sources references={references} />
    </article>
  );
}

function MessageHistory({ messages }: { messages: Message[] }) {
  return (
    <>
      {messages.map((message) =>
        message.role === "user" ? (
          <div className="flex justify-end" key={message.id}>
            <p className="bg-subtle max-w-[86%] rounded-[var(--radius-xl)] px-4 py-3 text-base leading-6 lg:max-w-[80%] lg:rounded-[var(--radius-lg)] lg:text-sm">
              {message.content}
            </p>
          </div>
        ) : (
          <AssistantMessage
            activities={message.trace?.activities ?? []}
            content={message.content}
            key={message.id}
            references={message.references}
            sourceTotal={
              message.trace?.citation_summary?.source_count ??
              sourceCount(message.references)
            }
            state="complete"
            failure={null}
          />
        ),
      )}
    </>
  );
}

export function ConversationView({
  title,
  messages,
  liveTurn,
  context,
  papers,
  projects,
  reasoningLevel,
  loading,
  error,
  onContextChange,
  onReasoningLevelChange,
  onSubmit,
  onStop,
  onRetry,
  canSend,
  readOnlyReason,
  composerForm,
  showComposer = true,
}: {
  title?: string;
  messages: Message[];
  liveTurn: LiveTurn | null;
  context: ResearchContext;
  papers: LibraryPaper[];
  projects: Project[];
  reasoningLevel: ReasoningLevel;
  loading?: boolean;
  error?: boolean;
  onContextChange: (context: ResearchContext) => void;
  onReasoningLevelChange: (level: ReasoningLevel) => void;
  onSubmit: (message: string) => Promise<void>;
  onStop: () => void;
  onRetry: () => void;
  canSend: boolean;
  readOnlyReason?: string | null;
  composerForm?: UseFormReturn<ComposerValues>;
  showComposer?: boolean;
}) {
  const t = useTranslations("Home.conversation");
  const rootRef = React.useRef<HTMLDivElement>(null);
  const scrollAnchor = React.useRef<HTMLDivElement>(null);
  const nearBottom = React.useRef(true);
  const visibleMessages = React.useMemo(
    () =>
      liveTurn
        ? messages.filter((message) => message.turn_id !== liveTurn.turnId)
        : messages,
    [liveTurn, messages],
  );
  const activitySignature = liveTurn?.activities
    .map((activity) => `${activity.id}:${activity.state}`)
    .join("|");

  React.useEffect(() => {
    const scrollRoot = rootRef.current?.closest("main");
    if (!scrollRoot) return;
    const scroller = scrollRoot;
    function updateProximity() {
      nearBottom.current =
        scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight <
        120;
    }
    updateProximity();
    scroller.addEventListener("scroll", updateProximity, { passive: true });
    return () => scroller.removeEventListener("scroll", updateProximity);
  }, []);

  React.useEffect(() => {
    if (!nearBottom.current) return;
    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    scrollAnchor.current?.scrollIntoView({
      behavior: reducedMotion ? "auto" : "smooth",
      block: "end",
    });
  }, [activitySignature, liveTurn?.content, visibleMessages.length]);

  return (
    <div
      className="mx-auto flex min-h-full w-full max-w-[848px] flex-col px-3 sm:px-8"
      ref={rootRef}
    >
      <header className="border-line sticky top-0 z-10 hidden h-16 shrink-0 items-center border-b bg-[color-mix(in_oklab,var(--color-bg-canvas)_92%,transparent)] px-1 backdrop-blur lg:flex">
        <h1 className="truncate text-sm font-medium">
          {title || t("assistant")}
        </h1>
      </header>
      <div className="flex-1 pt-6 pb-10 lg:py-8 lg:pb-40">
        {loading ? (
          <p className="text-muted py-12 text-center text-sm" role="status">
            {t("loading")}
          </p>
        ) : error ? (
          <div
            className="grid place-items-center py-12 text-center"
            role="alert"
          >
            <Icon glyph={WarningTriangle} size={24} tone="secondary" />
            <p className="mt-3 text-sm font-medium">{t("error")}</p>
            <Button
              className="mt-4"
              onClick={onRetry}
              size="sm"
              variant="secondary"
            >
              {t("retry")}
            </Button>
          </div>
        ) : visibleMessages.length === 0 && !liveTurn ? (
          <p className="text-muted py-12 text-center text-sm">{t("empty")}</p>
        ) : (
          <div className="grid gap-9 lg:gap-8">
            <MessageHistory messages={visibleMessages} />
            {liveTurn && (
              <>
                <div className="flex justify-end">
                  <p className="bg-subtle max-w-[86%] rounded-[var(--radius-xl)] px-4 py-3 text-base leading-6 lg:max-w-[80%] lg:rounded-[var(--radius-lg)] lg:text-sm">
                    {liveTurn.userMessage}
                  </p>
                </div>
                <AssistantMessage
                  activities={liveTurn.activities}
                  content={liveTurn.content}
                  onActivityOpenChange={(open) => {
                    if (open) nearBottom.current = false;
                  }}
                  references={liveTurn.references}
                  sourceTotal={
                    liveTurn.trace?.citation_summary?.source_count ??
                    sourceCount(liveTurn.references)
                  }
                  state={liveTurn.state}
                  failure={liveTurn.failure}
                />
              </>
            )}
            <div ref={scrollAnchor} />
          </div>
        )}
      </div>
      {!loading && !error && !canSend && (
        <div
          className="border-line bg-subtle mx-4 mb-3 rounded-[var(--radius-md)] border px-3 py-2 text-center text-xs"
          role="status"
        >
          {readOnlyReason ? t("readOnlyReason") : t("readOnly")}
        </div>
      )}
      {showComposer && (
        <div className="pointer-events-none sticky bottom-0 z-20 -mx-3 flex justify-center bg-[linear-gradient(to_top,var(--color-bg-canvas)_78%,transparent)] px-3 pt-5 pb-3 sm:-mx-8 lg:mx-0 lg:px-4 lg:pt-10 lg:pb-6">
          <div className="pointer-events-auto w-full max-w-[720px]">
            <ResearchComposer
              busy={liveTurn?.state === "streaming"}
              compact
              context={context}
              form={composerForm}
              onContextChange={onContextChange}
              onReasoningLevelChange={onReasoningLevelChange}
              onStop={onStop}
              onSubmit={onSubmit}
              papers={papers}
              projects={projects}
              reasoningLevel={reasoningLevel}
              unavailable={loading || error || !canSend}
            />
          </div>
        </div>
      )}
    </div>
  );
}
