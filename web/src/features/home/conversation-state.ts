import type { components } from "@/lib/api/generated/schema";
import { ApiError } from "@/lib/api/errors";
import type { ConversationStreamEvent } from "./api/conversations";

export type ConversationActivity =
  components["schemas"]["ConversationActivity"];
export type ConversationProgressEntry =
  components["schemas"]["ConversationProgressEntry"];
export type ConversationTrace = components["schemas"]["ConversationTrace"];
export type ConversationTraceEntry =
  ConversationProgressEntry | ConversationActivity;
export type ConversationAssistantItem =
  components["schemas"]["ConversationAssistantItem"];
export type ProvisionalAssistantItem = Omit<
  ConversationAssistantItem,
  "phase"
> & { phase: "provisional" };
export type ConversationFailure = {
  code?: string;
  kind?: string;
  retryable: boolean;
  correlationId?: string;
  diagnosticId?: string;
};

export type LiveTurn = {
  turnId: string;
  userMessage: string;
  content: string;
  entries: ConversationTraceEntry[];
  provisionalItems: ProvisionalAssistantItem[];
  completedItemIds: string[];
  trace: ConversationTrace | null;
  references: Record<string, unknown> | null;
  failure: ConversationFailure | null;
  state: "streaming" | "complete" | "cancelled" | "error";
};

export function createLiveTurn(turnId: string, userMessage: string): LiveTurn {
  return {
    turnId,
    userMessage,
    content: "",
    entries: [],
    provisionalItems: [],
    completedItemIds: [],
    trace: null,
    references: null,
    failure: null,
    state: "streaming",
  };
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : undefined;
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : undefined;
}

export function conversationFailureFromValue(
  value: unknown,
): ConversationFailure {
  const payload = record(value);
  return {
    code: stringValue(payload?.code),
    kind: stringValue(payload?.kind),
    retryable: payload?.retryable === true,
    correlationId: stringValue(payload?.correlation_id),
    diagnosticId: stringValue(payload?.diagnostic_id),
  };
}

export function conversationFailureFromError(
  error: unknown,
): ConversationFailure {
  if (!(error instanceof ApiError)) return { retryable: false };
  const payload = record(error.details);
  return {
    ...conversationFailureFromValue(payload),
    code: error.code ?? stringValue(payload?.code),
    correlationId: error.correlationId ?? stringValue(payload?.correlation_id),
  };
}

function updateEntry(
  entries: ConversationTraceEntry[],
  entry: ConversationTraceEntry,
) {
  const existing = entries.find((item) => item.id === entry.id);
  if (
    existing?.kind === "activity" &&
    entry.kind === "activity" &&
    existing.state !== "running" &&
    entry.state === "running"
  ) {
    return entries;
  }
  return [...entries.filter((item) => item.id !== entry.id), entry].sort(
    (left, right) => left.sequence - right.sequence,
  );
}

function completeAssistantItem(
  current: LiveTurn,
  item: ConversationAssistantItem,
) {
  if (current.completedItemIds.includes(item.id)) return current;
  const completedItemIds = [...current.completedItemIds, item.id];
  const provisionalItems = current.provisionalItems.filter(
    (candidate) => candidate.id !== item.id,
  );
  if (item.phase === "progress") {
    if (!item.content) {
      return { ...current, completedItemIds, provisionalItems };
    }
    return {
      ...current,
      completedItemIds,
      provisionalItems,
      entries: updateEntry(current.entries, {
        kind: "progress",
        id: item.id,
        sequence: item.sequence,
        content: item.content,
      }),
    };
  }
  return {
    ...current,
    completedItemIds,
    provisionalItems,
    content: item.content,
  };
}

export function reduceLiveTurn(
  current: LiveTurn | null,
  event: ConversationStreamEvent,
): LiveTurn | null {
  if (!current) return current;
  if (current.state !== "streaming") return current;
  switch (event.type) {
    case "activity":
      return {
        ...current,
        entries: updateEntry(current.entries, event.activity),
      };
    case "assistant_item_start":
      if (
        current.completedItemIds.includes(event.item_id) ||
        current.provisionalItems.some((item) => item.id === event.item_id)
      ) {
        return current;
      }
      return {
        ...current,
        provisionalItems: [
          ...current.provisionalItems,
          {
            id: event.item_id,
            sequence: event.sequence,
            phase: "provisional" as const,
            content: "",
          },
        ].sort((left, right) => left.sequence - right.sequence),
      };
    case "assistant_item_delta":
      if (current.completedItemIds.includes(event.item_id)) return current;
      return {
        ...current,
        provisionalItems: current.provisionalItems.map((item) =>
          item.id === event.item_id
            ? { ...item, content: item.content + event.delta }
            : item,
        ),
      };
    case "assistant_item_complete":
      return completeAssistantItem(current, event.item);
    case "references":
      return {
        ...current,
        references: event.references as Record<string, unknown>,
      };
    case "complete":
      return {
        ...current,
        entries: event.trace?.entries ?? current.entries,
        trace: event.trace ?? current.trace,
        state: "complete",
      };
    case "error":
      return {
        ...current,
        failure: conversationFailureFromValue(event.error),
        state: "error",
      };
    case "start":
      return current;
  }
}
