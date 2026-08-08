"use client";

import {
  Copy,
  NavArrowDown,
  NavArrowLeft,
  NavArrowRight,
  Page,
  RefreshDouble,
  WarningTriangle,
} from "iconoir-react";
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

export type ConversationTurn =
  components["schemas"]["ConversationTurnResponse"];
export type ConversationResponseVariant =
  components["schemas"]["ConversationResponseVariantResponse"];
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
  response,
  variants,
  canRetry,
  canSwitch,
  onRetryResponse,
  onSelectResponse,
  onUseSuggestion,
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
  response?: ConversationResponseVariant;
  variants?: ConversationResponseVariant[];
  canRetry?: boolean;
  canSwitch?: boolean;
  onRetryResponse?: () => void;
  onSelectResponse?: (responseId: string) => void;
  onUseSuggestion?: (suggestion: string) => void;
}) {
  const t = useTranslations("Home.conversation");
  const [copied, setCopied] = React.useState(false);
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
      {response?.status === "completed" && visibleContent && (
        <div
          className="flex min-h-10 items-center gap-1"
          role="group"
          aria-label={t("answerActions")}
        >
          <IconButton
            label={copied ? t("copied") : t("copy")}
            onClick={() => {
              void (async () => {
                try {
                  await navigator.clipboard.writeText(visibleContent);
                  setCopied(true);
                  window.setTimeout(() => setCopied(false), 1500);
                } catch {
                  // Clipboard access may be denied outside a secure context.
                }
              })();
            }}
            variant="ghost"
          >
            <Icon glyph={Copy} size={20} tone="secondary" />
          </IconButton>
          {canRetry && onRetryResponse && (
            <IconButton
              label={t("regenerate")}
              onClick={onRetryResponse}
              variant="ghost"
            >
              <Icon glyph={RefreshDouble} size={20} tone="secondary" />
            </IconButton>
          )}
          {canSwitch &&
            variants &&
            variants.length > 1 &&
            onSelectResponse &&
            (() => {
              const ordered = [...variants].sort(
                (left, right) => left.variant_index - right.variant_index,
              );
              const index = ordered.findIndex(
                (candidate) => candidate.id === response.id,
              );
              return (
                <div className="text-muted ml-1 flex items-center gap-0.5 text-xs">
                  <IconButton
                    disabled={index <= 0}
                    label={t("previousResponse")}
                    onClick={() => onSelectResponse(ordered[index - 1]!.id)}
                    variant="ghost"
                  >
                    <Icon glyph={NavArrowLeft} size={16} />
                  </IconButton>
                  <span
                    aria-label={t("responseVersion", {
                      current: index + 1,
                      total: ordered.length,
                    })}
                  >
                    {index + 1}/{ordered.length}
                  </span>
                  <IconButton
                    disabled={index >= ordered.length - 1}
                    label={t("nextResponse")}
                    onClick={() => onSelectResponse(ordered[index + 1]!.id)}
                    variant="ghost"
                  >
                    <Icon glyph={NavArrowRight} size={16} />
                  </IconButton>
                </div>
              );
            })()}
          <span className="sr-only" aria-live="polite">
            {copied ? t("copied") : ""}
          </span>
        </div>
      )}
      {response?.suggestions_status === "completed" &&
        response.suggestions?.length === 3 &&
        onUseSuggestion && (
          <div
            className="grid justify-items-start gap-2 pt-1"
            aria-label={t("suggestions")}
          >
            {response.suggestions.map((suggestion) => (
              <button
                className="bg-subtle hover:bg-hover min-h-11 rounded-full px-4 py-2 text-left text-sm transition-colors"
                key={suggestion}
                onClick={() => onUseSuggestion(suggestion)}
                type="button"
              >
                {suggestion}
              </button>
            ))}
          </div>
        )}
    </article>
  );
}

function selectedResponse(turn: ConversationTurn) {
  return (
    turn.responses.find(
      (response) => response.id === turn.selected_response_id,
    ) ??
    [...turn.responses].sort(
      (left, right) => right.variant_index - left.variant_index,
    )[0]
  );
}

function MessageHistory({
  turns,
  liveTurn,
  canSend,
  onRetryResponse,
  onSelectResponse,
  onUseSuggestion,
}: {
  turns: ConversationTurn[];
  liveTurn: LiveTurn | null;
  canSend: boolean;
  onRetryResponse: (turn: ConversationTurn) => void;
  onSelectResponse: (turnId: string, responseId: string) => void;
  onUseSuggestion: (suggestion: string) => void;
}) {
  const latestTurnId = turns.at(-1)?.id;
  return (
    <>
      {turns.map((turn) => {
        const response = selectedResponse(turn);
        const isLive = liveTurn?.turnId === turn.id;
        return (
          <React.Fragment key={turn.id}>
            <div className="flex justify-end">
              <p className="bg-subtle max-w-[86%] rounded-[var(--radius-xl)] px-4 py-3 text-base leading-6 lg:max-w-[80%] lg:rounded-[var(--radius-lg)] lg:text-sm">
                {turn.user_query}
              </p>
            </div>
            {isLive && liveTurn ? (
              <AssistantMessage
                content={liveTurn.content}
                entries={liveTurn.entries}
                failure={liveTurn.failure}
                provisionalContent={liveTurn.provisionalItems
                  .map((item) => item.content)
                  .join("")}
                references={liveTurn.references}
                sourceTotal={
                  liveTurn.trace?.citation_summary?.source_count ??
                  sourceCount(liveTurn.references)
                }
                state={liveTurn.state}
              />
            ) : response ? (
              <AssistantMessage
                canRetry={turn.id === latestTurnId && canSend}
                canSwitch={turn.id === latestTurnId}
                content={response.content ?? ""}
                entries={response.trace?.entries ?? []}
                historical
                onRetryResponse={() => onRetryResponse(turn)}
                onSelectResponse={(responseId) =>
                  onSelectResponse(turn.id, responseId)
                }
                onUseSuggestion={
                  turn.id === latestTurnId ? onUseSuggestion : undefined
                }
                references={response.references}
                response={response}
                sourceTotal={
                  response.trace?.citation_summary?.source_count ??
                  sourceCount(response.references)
                }
                state="complete"
                failure={null}
                variants={turn.responses}
              />
            ) : null}
          </React.Fragment>
        );
      })}
    </>
  );
}

export function ConversationView({
  title,
  turns,
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
  onRetryResponse,
  onSelectResponse,
  onUseSuggestion,
  canSend,
  readOnlyReason,
  composerForm,
  showComposer = true,
}: {
  title?: string;
  turns: ConversationTurn[];
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
  onRetryResponse: (turn: ConversationTurn) => void;
  onSelectResponse: (turnId: string, responseId: string) => void;
  onUseSuggestion: (suggestion: string) => void;
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
  const visibleTurns = React.useMemo(
    () =>
      liveTurn?.generationKind === "initial"
        ? turns.filter((turn) => turn.id !== liveTurn.turnId)
        : turns,
    [liveTurn, turns],
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
    visibleTurns.length,
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
        ) : visibleTurns.length === 0 && !liveTurn ? (
          <p className="text-muted py-12 text-center text-sm">{t("empty")}</p>
        ) : (
          <div className="grid gap-9 lg:gap-8">
            <MessageHistory
              canSend={canSend && liveTurn?.state !== "streaming"}
              liveTurn={liveTurn}
              onRetryResponse={onRetryResponse}
              onSelectResponse={onSelectResponse}
              onUseSuggestion={onUseSuggestion}
              turns={visibleTurns}
            />
            {liveTurn?.generationKind === "initial" && (
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
