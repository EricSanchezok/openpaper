import type { components } from "@/lib/api/generated/schema";
import { ApiError } from "@/lib/api/errors";
import type { ConversationStreamEvent } from "./api/conversations";

export type ConversationActivity =
  components["schemas"]["ConversationActivity"];
export type ConversationTrace = components["schemas"]["ConversationTrace"];
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
  activities: ConversationActivity[];
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
    activities: [],
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

function updateActivity(
  activities: ConversationActivity[],
  activity: ConversationActivity,
) {
  const existing = activities.find((item) => item.id === activity.id);
  if (
    existing &&
    existing.state !== "running" &&
    activity.state === "running"
  ) {
    return activities;
  }
  return [
    ...activities.filter((item) => item.id !== activity.id),
    activity,
  ].sort((left, right) => left.sequence - right.sequence);
}

export function reduceLiveTurn(
  current: LiveTurn | null,
  event: ConversationStreamEvent,
): LiveTurn | null {
  if (!current) return current;
  switch (event.type) {
    case "activity":
      return {
        ...current,
        activities: updateActivity(current.activities, event.activity),
      };
    case "content_delta":
      return { ...current, content: current.content + event.delta };
    case "references":
      return {
        ...current,
        references: event.references as Record<string, unknown>,
      };
    case "complete":
      return {
        ...current,
        activities: event.trace?.activities ?? current.activities,
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
