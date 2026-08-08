export const homeKeys = {
  all: ["home"] as const,
  conversations: () => [...homeKeys.all, "conversations"] as const,
  conversation: (conversationId: string) =>
    [...homeKeys.conversations(), conversationId] as const,
  messages: (conversationId: string) =>
    [...homeKeys.conversation(conversationId), "messages"] as const,
  papers: () => [...homeKeys.all, "papers"] as const,
  projects: () => [...homeKeys.all, "projects"] as const,
};
