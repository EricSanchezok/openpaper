"use client";

import { NavArrowDown, Page, WarningTriangle } from "iconoir-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import type {
  ConversationActivity,
  ConversationFailure,
  ConversationTraceEntry,
  LiveTurn,
} from "../conversation-state";

type ActivityBatch = {
  kind: "batch";
  id: string;
  sequence: number;
  activities: ConversationActivity[];
};

export type WorklogRow =
  Extract<ConversationTraceEntry, { kind: "progress" }> | ActivityBatch;

export function groupWorklogEntries(
  entries: ConversationTraceEntry[],
): WorklogRow[] {
  const rows: WorklogRow[] = [];
  for (const entry of [...entries].sort(
    (left, right) => left.sequence - right.sequence,
  )) {
    if (entry.kind === "progress") {
      rows.push(entry);
      continue;
    }
    const previous = rows.at(-1);
    if (previous?.kind === "batch") {
      previous.activities.push(entry);
    } else {
      rows.push({
        kind: "batch",
        id: `batch:${entry.id}`,
        sequence: entry.sequence,
        activities: [entry],
      });
    }
  }
  return rows;
}

function activities(entries: ConversationTraceEntry[]) {
  return entries.filter(
    (entry): entry is ConversationActivity => entry.kind === "activity",
  );
}

function worklogSummary(
  entries: ConversationTraceEntry[],
  state: LiveTurn["state"],
  sources: number,
  failure: ConversationFailure | null,
  t: ReturnType<typeof useTranslations<"Home.conversation">>,
) {
  const operations = activities(entries);
  if (state === "cancelled") return t("activity.stopped");
  if (state === "error") {
    if (failure?.code?.endsWith("_unavailable")) {
      return t("failure.unavailable");
    }
    if (failure?.kind === "rate_limited") return t("failure.rateLimited");
    return t("activity.failed");
  }
  const running = operations.findLast(
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
    return t("activity.thinking");
  }
  const failed = operations.some((activity) => activity.state === "failed");
  return t(failed ? "activity.partialSummary" : "activity.completeSummary", {
    count: operations.length,
    sources,
  });
}

function batchLabel(
  batch: ActivityBatch,
  t: ReturnType<typeof useTranslations<"Home.conversation">>,
) {
  const counts = new Map<ConversationActivity["category"], number>();
  for (const activity of batch.activities) {
    counts.set(activity.category, (counts.get(activity.category) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([category, count]) =>
      t(`activity.batch.${category}`, {
        count,
        connector:
          batch.activities.find((item) => item.category === "connector")
            ?.connector_name || t("activity.connectorFallback"),
      }),
    )
    .join(" · ");
}

function ActivityBatchRow({ batch }: { batch: ActivityBatch }) {
  const t = useTranslations("Home.conversation");
  const failed = batch.activities.some(
    (activity) => activity.state === "failed",
  );
  const subjects = [
    ...new Set(
      batch.activities
        .map((activity) => activity.subject?.trim())
        .filter((subject): subject is string => Boolean(subject)),
    ),
  ];
  const visibleSubjects = subjects.slice(0, 2);
  const remaining = subjects.length - visibleSubjects.length;

  return (
    <li className="flex min-w-0 gap-2.5 py-1">
      <Icon
        className="mt-0.5 shrink-0"
        glyph={failed ? WarningTriangle : Page}
        size={16}
        tone="secondary"
      />
      <span className="min-w-0 flex-1">
        <span className="text-foreground block text-sm font-medium lg:text-xs">
          {batchLabel(batch, t)}
        </span>
        {visibleSubjects.length > 0 && (
          <span className="text-muted mt-0.5 block text-sm leading-5 break-words lg:text-xs">
            {visibleSubjects.join(" · ")}
            {remaining > 0
              ? ` · ${t("activity.more", { count: remaining })}`
              : ""}
          </span>
        )}
      </span>
      {failed && <span className="sr-only">{t("activity.state.failed")}</span>}
    </li>
  );
}

export function ConversationWorklog({
  entries,
  sourceTotal,
  state,
  failure,
  provisionalVisible,
  historical = false,
  onOpenChange,
}: {
  entries: ConversationTraceEntry[];
  sourceTotal: number;
  state: LiveTurn["state"];
  failure: ConversationFailure | null;
  provisionalVisible: boolean;
  historical?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const t = useTranslations("Home.conversation");
  const [manualOpen, setManualOpen] = React.useState<boolean | null>(null);
  const rows = React.useMemo(() => groupWorklogEntries(entries), [entries]);
  const hasHistory = rows.length > 0;
  const open =
    manualOpen ?? (!historical && state === "streaming" && hasHistory);
  const visible =
    hasHistory ||
    state === "cancelled" ||
    state === "error" ||
    (state === "streaming" && !provisionalVisible);
  const summary = worklogSummary(entries, state, sourceTotal, failure, t);

  if (!visible) return null;

  function toggle() {
    if (!hasHistory) return;
    const next = !open;
    setManualOpen(next);
    onOpenChange?.(next);
  }

  return (
    <section className="text-secondary text-base lg:text-sm" data-state={state}>
      {hasHistory ? (
        <button
          aria-expanded={open}
          className="hover:text-foreground focus-visible:text-foreground flex min-h-11 w-full items-center gap-2 rounded-[var(--radius-sm)] text-left transition-colors motion-reduce:transition-none lg:min-h-8"
          onClick={toggle}
          type="button"
        >
          <span
            aria-live="polite"
            className="activity-copy-enter min-w-0 flex-1"
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
        <ol className="mt-1 grid gap-1 pb-1">
          {rows.map((row) =>
            row.kind === "progress" ? (
              <li
                className="text-foreground py-1 text-sm leading-6 lg:text-xs lg:leading-5"
                key={row.id}
              >
                {row.content}
              </li>
            ) : (
              <ActivityBatchRow batch={row} key={row.id} />
            ),
          )}
        </ol>
      )}
      {state === "error" && failure?.diagnosticId && (
        <p className="text-muted mt-1 text-xs">
          {t("failure.diagnostic", { id: failure.diagnosticId })}
        </p>
      )}
    </section>
  );
}
