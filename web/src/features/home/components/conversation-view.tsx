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
import {
  ResearchComposer,
  type ReasoningLevel,
  type ResearchContext,
} from "./research-composer";

type Message =
  components["schemas"]["app__modules__conversations__application__contracts__conversations__MessageResponse"];
type LibraryPaper = components["schemas"]["LibraryPaperResponse"];
type Project = components["schemas"]["ProjectResponse"];
type ReferenceBundle = components["schemas"]["ReferenceBundle"];

export type LiveTurn = {
  userMessage: string;
  content: string;
  statuses: string[];
  reasoning: string;
  references: Record<string, unknown> | null;
  state: "streaming" | "complete" | "cancelled" | "error";
};

function isReferenceBundle(value: unknown): value is ReferenceBundle {
  return Boolean(
    value &&
    typeof value === "object" &&
    Array.isArray((value as { sources?: unknown }).sources),
  );
}

function statusMessages(trace: Message["trace"]): string[] {
  if (!trace) return [];
  const value = trace.status_messages;
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function reasoningContent(trace: Message["trace"]) {
  return trace && typeof trace.reasoning_content === "string"
    ? trace.reasoning_content
    : "";
}

function ProcessDisclosure({
  statuses,
  reasoning,
  streaming,
}: {
  statuses: string[];
  reasoning: string;
  streaming?: boolean;
}) {
  const t = useTranslations("Home.conversation");
  const [open, setOpen] = React.useState(false);
  if (statuses.length === 0 && !reasoning) return null;

  return (
    <div className="bg-subtle rounded-[var(--radius-md)] p-3">
      <button
        aria-expanded={open}
        className="flex w-full items-center gap-2 text-left text-[13px] font-medium"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <Icon
          glyph={streaming ? Page : CheckCircle}
          size={16}
          tone="secondary"
        />
        <span className="min-w-0 flex-1 truncate">
          {statuses.at(-1) || t("process")}
        </span>
        <Icon
          className={cn(
            "transition-transform motion-reduce:transition-none",
            open && "rotate-180",
          )}
          glyph={NavArrowDown}
          size={16}
          tone="secondary"
        />
      </button>
      {open && (
        <div className="border-line mt-3 grid gap-2 border-t pt-3">
          {statuses.map((status, index) => (
            <div
              className="text-secondary flex gap-2 text-xs"
              key={`${status}-${index}`}
            >
              <span className="bg-line mt-1.5 size-1.5 shrink-0 rounded-full" />
              <span>{status}</span>
            </div>
          ))}
          {reasoning && (
            <details className="text-secondary text-xs">
              <summary className="cursor-pointer font-medium">
                {t("reasoning")}
              </summary>
              <p className="mt-2 whitespace-pre-wrap">{reasoning}</p>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

function Sources({ references }: { references: unknown }) {
  const t = useTranslations("Home.conversation");
  if (!isReferenceBundle(references) || !references.sources?.length) {
    return null;
  }
  const sources = references.sources ?? [];
  return (
    <section className="mt-5">
      <div className="mb-2 flex items-center gap-2 text-[13px] font-medium">
        {t("sources")}
        <span className="text-muted text-xs font-normal">{sources.length}</span>
      </div>
      <div className="grid gap-2">
        {sources.map((source, index) => {
          const title =
            "title" in source && source.title
              ? source.title
              : t("reference", { number: index + 1 });
          const content = source.reference;
          const row = (
            <>
              <span className="bg-subtle grid size-6 shrink-0 place-items-center rounded text-xs">
                {index + 1}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium">
                  {title}
                </span>
                <span className="text-muted mt-0.5 line-clamp-1 block text-[11px]">
                  {content}
                </span>
              </span>
            </>
          );
          return source.kind === "external" ? (
            <a
              className="border-line hover:bg-hover flex items-center gap-2 rounded-[var(--radius-md)] border p-2"
              href={source.url}
              key={`${source.key}-${source.url}`}
              rel="noreferrer"
              target="_blank"
            >
              {row}
            </a>
          ) : (
            <div
              className="border-line flex items-center gap-2 rounded-[var(--radius-md)] border p-2"
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
  content,
  statuses,
  reasoning,
  references,
  streaming,
}: {
  content: string;
  statuses: string[];
  reasoning: string;
  references: unknown;
  streaming?: boolean;
}) {
  const t = useTranslations("Home.conversation");
  return (
    <article className="grid gap-3">
      <div className="flex items-center gap-2 text-xs font-medium">
        <span className="bg-primary text-primary-foreground grid size-6 place-items-center rounded-full">
          S
        </span>
        {t("assistant")}
      </div>
      <ProcessDisclosure
        reasoning={reasoning}
        statuses={statuses}
        streaming={streaming}
      />
      {content ? (
        <p className="text-sm leading-7 whitespace-pre-wrap">{content}</p>
      ) : streaming ? (
        <p className="text-muted animate-pulse text-sm" role="status">
          {t("working")}
        </p>
      ) : null}
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
            <p className="bg-subtle max-w-[80%] rounded-[var(--radius-lg)] px-4 py-3 text-sm leading-6">
              {message.content}
            </p>
          </div>
        ) : (
          <AssistantMessage
            content={message.content}
            key={message.id}
            reasoning={reasoningContent(message.trace)}
            references={message.references}
            statuses={statusMessages(message.trace)}
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
}) {
  const t = useTranslations("Home.conversation");
  const scrollAnchor = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    scrollAnchor.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [liveTurn?.content, liveTurn?.statuses.length, messages.length]);

  return (
    <div className="mx-auto flex min-h-full w-full max-w-[848px] flex-col px-4 sm:px-8">
      <header className="border-line sticky top-0 z-10 flex h-14 shrink-0 items-center border-b bg-[color-mix(in_srgb,var(--color-bg-canvas)_92%,transparent)] px-1 backdrop-blur lg:h-16">
        <h1 className="truncate text-sm font-medium">
          {title || t("assistant")}
        </h1>
      </header>
      <div className="flex-1 py-8 pb-40">
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
        ) : messages.length === 0 && !liveTurn ? (
          <p className="text-muted py-12 text-center text-sm">{t("empty")}</p>
        ) : (
          <div className="grid gap-8">
            <MessageHistory messages={messages} />
            {liveTurn && (
              <>
                <div className="flex justify-end">
                  <p className="bg-subtle max-w-[80%] rounded-[var(--radius-lg)] px-4 py-3 text-sm leading-6">
                    {liveTurn.userMessage}
                  </p>
                </div>
                <AssistantMessage
                  content={liveTurn.content}
                  reasoning={liveTurn.reasoning}
                  references={liveTurn.references}
                  statuses={liveTurn.statuses}
                  streaming={liveTurn.state === "streaming"}
                />
                {liveTurn.state !== "streaming" && (
                  <p
                    className={cn(
                      "text-sm",
                      liveTurn.state === "error" ? "text-danger" : "text-muted",
                    )}
                    role={liveTurn.state === "error" ? "alert" : "status"}
                  >
                    {liveTurn.state === "error" ? t("error") : t("cancelled")}
                  </p>
                )}
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
      <div className="pointer-events-none sticky bottom-0 z-20 flex justify-center bg-[linear-gradient(to_top,var(--color-bg-canvas)_72%,transparent)] px-4 pt-10 pb-6">
        <div className="pointer-events-auto w-full max-w-[720px]">
          <ResearchComposer
            busy={liveTurn?.state === "streaming"}
            compact
            context={context}
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
    </div>
  );
}
