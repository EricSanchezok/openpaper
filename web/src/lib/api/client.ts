import createClient from "openapi-fetch";

import type { paths } from "@/lib/api/generated/schema";
import { clientEnvironment } from "@/lib/env/client";
import { toApiError } from "./errors";

export type ApiClientOptions = {
  baseUrl?: string;
  getAccessToken?: () => string | undefined | Promise<string | undefined>;
  onUnauthorized?: () => void | Promise<void>;
};

export function createApiClient(options: ApiClientOptions = {}) {
  const client = createClient<paths>({
    baseUrl: options.baseUrl ?? clientEnvironment.NEXT_PUBLIC_API_URL,
    credentials: "include",
  });

  client.use({
    async onRequest({ request }) {
      const token = await options.getAccessToken?.();
      if (token) request.headers.set("Authorization", `Bearer ${token}`);
      return request;
    },
    async onResponse({ response }) {
      if (response.status === 401) await options.onUnauthorized?.();
      if (!response.ok) throw await toApiError(response);
      return response;
    },
  });

  return client;
}

export const apiClient = createApiClient();
