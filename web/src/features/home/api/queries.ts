import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/lib/api";
import { homeKeys } from "./keys";

export const homeQueries = {
  conversations: () =>
    queryOptions({
      queryKey: homeKeys.conversations(),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/conversations", {
          params: { query: { archived: false, limit: 50 } },
          signal,
        });
        if (!data) throw new Error("Conversation list response was empty");
        return data;
      },
    }),
  conversation: (conversationId: string) =>
    queryOptions({
      queryKey: homeKeys.conversation(conversationId),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/conversations/{conversation_id}",
          { params: { path: { conversation_id: conversationId } }, signal },
        );
        if (!data) throw new Error("Conversation response was empty");
        return data;
      },
    }),
  turns: (conversationId: string) =>
    queryOptions({
      queryKey: homeKeys.turns(conversationId),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/conversations/{conversation_id}/turns",
          {
            params: {
              path: { conversation_id: conversationId },
              query: { limit: 100 },
            },
            signal,
          },
        );
        if (!data) throw new Error("Conversation turns response was empty");
        return data;
      },
    }),
  papers: () =>
    queryOptions({
      queryKey: homeKeys.papers(),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/library/papers", {
          signal,
        });
        if (!data) throw new Error("Library response was empty");
        return data;
      },
    }),
  projects: () =>
    queryOptions({
      queryKey: homeKeys.projects(),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/projects", {
          params: { query: { limit: 12 } },
          signal,
        });
        if (!data) throw new Error("Project list response was empty");
        return data;
      },
    }),
};
