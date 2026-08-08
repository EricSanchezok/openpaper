import type { components } from "@/lib/api/generated/schema";
import { apiClient, authenticatedFetch, toApiError } from "@/lib/api";
import { clientEnvironment } from "@/lib/env/client";

export type ConversationStreamEvent =
  components["schemas"]["ConversationStreamEventSchema"];
export type ConversationMessageRequest =
  components["schemas"]["ConversationMessageRequest"];
export type ConversationCreateRequest =
  components["schemas"]["ConversationCreateRequest"];

const conversationStreamEventTypes = {
  start: true,
  activity: true,
  assistant_item_start: true,
  assistant_item_delta: true,
  assistant_item_complete: true,
  references: true,
  complete: true,
  error: true,
} satisfies Record<ConversationStreamEvent["type"], true>;

export async function createConversation(body: ConversationCreateRequest) {
  const { data } = await apiClient.POST("/api/v1/conversations", { body });
  if (!data) throw new Error("Create conversation response was empty");
  return data;
}

export async function updateConversationContext(
  conversationId: string,
  context:
    | components["schemas"]["LibraryPaperContext"]
    | components["schemas"]["SelectedPaperContext"],
) {
  const { data } = await apiClient.PUT(
    "/api/v1/conversations/{conversation_id}/context",
    {
      params: { path: { conversation_id: conversationId } },
      body: context,
    },
  );
  if (!data) throw new Error("Update conversation context response was empty");
  return data;
}

export function parseConversationEventBlock(
  block: string,
): ConversationStreamEvent | undefined {
  const data = block
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!data) return undefined;
  const value: unknown = JSON.parse(data);
  if (
    !value ||
    typeof value !== "object" ||
    !("type" in value) ||
    typeof value.type !== "string" ||
    !(value.type in conversationStreamEventTypes)
  ) {
    throw new Error("Conversation stream event was malformed");
  }
  return value as ConversationStreamEvent;
}

export async function streamConversationMessage({
  conversationId,
  message,
  signal,
  onEvent,
}: {
  conversationId: string;
  message: ConversationMessageRequest;
  signal: AbortSignal;
  onEvent: (event: ConversationStreamEvent) => void;
}) {
  const response = await authenticatedFetch(
    `${clientEnvironment.NEXT_PUBLIC_API_URL}/api/v1/conversations/${conversationId}/messages`,
    {
      method: "POST",
      credentials: "include",
      headers: {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(message),
      signal,
    },
  );
  if (!response.ok) throw await toApiError(response);
  if (!response.body) throw new Error("Conversation stream response was empty");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = false;

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const event = parseConversationEventBlock(block);
      if (!event || completed) continue;
      onEvent(event);
      if (event.type === "complete") completed = true;
      if (event.type === "error") completed = true;
    }
    if (done) break;
  }

  const trailing = parseConversationEventBlock(buffer);
  if (trailing && !completed) {
    onEvent(trailing);
    if (trailing.type === "complete" || trailing.type === "error") {
      completed = true;
    }
  }
  if (!completed) throw new Error("Conversation stream ended unexpectedly");
}
