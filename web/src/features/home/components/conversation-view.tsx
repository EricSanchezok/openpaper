"use client";

import { NavArrowDown, Page, WarningTriangle } from "iconoir-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button, IconButton } from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import type { components } from "@/lib/api/generated/schema";
import type {
  ConversationFailure,
  ConversationTraceEntry,
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
import { ConversationWorklog } from "./conversation-worklog";

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

function Sources({ references }: { references: unknown }) {
  const t = useTranslations("Home.conversation");
  if (!isReferenceBundle(references) || !references.sources?.length)
    return null;
  const sources = references.sources;

  function sourceRows(mobile: boolean) {
    return sources.map((source, index) => {
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
            <span
              className={
                mobile
                  ? "line-clamp-2 text-sm font-medium"
                  : "block truncate text-xs font-medium"
              }
            >
              {title}
            </span>
            <span className="text-caption text-muted mt-0.5 line-clamp-1 block">
              {source.reference}
            </span>
          </span>
        </>
      );
      const className = mobile
        ? "hover:bg-hover flex min-h-12 min-w-0 items-center gap-2 rounded-[var(--radius-md)] px-1 py-2"
        : "border-line hover:bg-hover flex items-center gap-2 rounded-[var(--radius-md)] border p-2";
      return source.kind === "external" ? (
        <a
          className={className}
          href={source.url}
          key={`${source.key}-${source.url}`}
          rel="noreferrer"
          target="_blank"
        >
          {row}
        </a>
      ) : (
        <div className={className} key={`${source.key}-${index}`}>
          {row}
        </div>
      );
    });
  }

  return (
    <section className="mt-5 min-w-0">
      <details className="group lg:hidden">
        <summary
          aria-label={t("showSources", { count: sources.length })}
          className="bg-subtle hover:bg-hover flex min-h-12 w-fit cursor-pointer list-none items-center gap-2 rounded-full px-3 text-sm font-medium [&::-webkit-details-marker]:hidden"
        >
          <Icon glyph={Page} size={16} tone="secondary" />
          <span>{t("sourceSummary", { count: sources.length })}</span>
          <Icon
            className="transition-transform duration-150 group-open:rotate-180 motion-reduce:transition-none"
            glyph={NavArrowDown}
            size={16}
            tone="secondary"
          />
        </summary>
        <div className="mt-2 grid gap-1">{sourceRows(true)}</div>
      </details>
      <div className="hidden lg:block">
        <div className="text-ui mb-2 flex items-center gap-2 font-medium">
          {t("sources")}
          <span className="text-muted text-xs font-normal">
            {sources.length}
          </span>
        </div>
        <div className="grid gap-2">{sourceRows(false)}</div>
      </div>
    </section>
  );
}

function AssistantMessage({
  entries,
  content,
  provisionalContent,
  references,
  sourceTotal,
  state,
  failure,
  historical,
  onActivityOpenChange,
}: {
  entries: ConversationTraceEntry[];
  content: string;
  provisionalContent?: string;
  references: unknown;
  sourceTotal: number;
  state: LiveTurn["state"];
  failure?: ConversationFailure | null;
  historical?: boolean;
  onActivityOpenChange?: (open: boolean) => void;
}) {
  const t = useTranslations("Home.conversation");
  const visibleContent = content || provisionalContent || "";
  const presentationState =
    content && state === "streaming" ? "complete" : state;
  return (
    <article aria-label={t("assistantMessage")} className="grid gap-3">
      <ConversationWorklog
        entries={entries}
        failure={failure ?? null}
        historical={historical}
        onOpenChange={onActivityOpenChange}
        provisionalVisible={Boolean(provisionalContent)}
        sourceTotal={sourceTotal}
        state={presentationState}
      />
      {visibleContent && <MessageContent content={visibleContent} />}
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
            content={message.content}
            entries={message.trace?.entries ?? []}
            historical
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
  const [showJumpToLatest, setShowJumpToLatest] = React.useState(false);
  const visibleMessages = React.useMemo(
    () =>
      liveTurn
        ? messages.filter((message) => message.turn_id !== liveTurn.turnId)
        : messages,
    [liveTurn, messages],
  );
  const worklogSignature = liveTurn?.entries
    .map((entry) =>
      entry.kind === "activity"
        ? `${entry.id}:${entry.state}`
        : `${entry.id}:${entry.content.length}`,
    )
    .join("|");
  const provisionalContent = liveTurn?.provisionalItems
    .map((item) => item.content)
    .join("");

  React.useEffect(() => {
    const scrollRoot = rootRef.current?.closest("main");
    if (!scrollRoot) return;
    const scroller = scrollRoot;
    function updateProximity() {
      const gap =
        scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
      const nextNearBottom = gap < 120;
      nearBottom.current = nextNearBottom;
      setShowJumpToLatest(
        scroller.scrollHeight > scroller.clientHeight + 32 && !nextNearBottom,
      );
    }
    const initialFrame = window.requestAnimationFrame(updateProximity);
    scroller.addEventListener("scroll", updateProximity, { passive: true });
    return () => {
      window.cancelAnimationFrame(initialFrame);
      scroller.removeEventListener("scroll", updateProximity);
    };
  }, []);

  React.useEffect(() => {
    if (!nearBottom.current) {
      setShowJumpToLatest(true);
      return;
    }
    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    scrollAnchor.current?.scrollIntoView({
      behavior: reducedMotion ? "auto" : "smooth",
      block: "end",
    });
  }, [
    worklogSignature,
    liveTurn?.content,
    provisionalContent,
    visibleMessages.length,
  ]);

  function jumpToLatest() {
    nearBottom.current = true;
    setShowJumpToLatest(false);
    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    scrollAnchor.current?.scrollIntoView({
      behavior: reducedMotion ? "auto" : "smooth",
      block: "end",
    });
  }

  return (
    <div
      className="mx-auto flex min-h-full w-full max-w-[848px] min-w-0 flex-col px-4 min-[390px]:px-5 sm:px-8"
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
                  content={liveTurn.content}
                  entries={liveTurn.entries}
                  key={liveTurn.turnId}
                  onActivityOpenChange={(open) => {
                    if (open) nearBottom.current = false;
                  }}
                  provisionalContent={provisionalContent}
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
      {showJumpToLatest && (
        <div className="pointer-events-none sticky bottom-3 z-10 -mt-15 hidden h-15 justify-center max-lg:flex">
          <IconButton
            className="bg-elevated shadow-raised pointer-events-auto size-12 rounded-full"
            label={t("jumpToLatest")}
            onClick={jumpToLatest}
            variant="secondary"
          >
            <Icon glyph={NavArrowDown} size={20} />
          </IconButton>
        </div>
      )}
      {!loading && !error && !canSend && (
        <div
          className="border-line bg-subtle mx-4 mb-3 rounded-[var(--radius-md)] border px-3 py-2 text-center text-xs"
          role="status"
        >
          {readOnlyReason ? t("readOnlyReason") : t("readOnly")}
        </div>
      )}
      {showComposer && (
        <div className="pointer-events-none sticky bottom-0 z-20 -mx-4 flex justify-center bg-[linear-gradient(to_top,var(--color-bg-canvas)_78%,transparent)] px-4 pt-5 pb-3 min-[390px]:-mx-5 min-[390px]:px-5 sm:-mx-8 lg:mx-0 lg:px-4 lg:pt-10 lg:pb-6">
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
