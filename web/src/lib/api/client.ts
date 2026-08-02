import createClient from "openapi-fetch";

import type { paths } from "@/lib/api/generated/schema";
import { clientEnvironment } from "@/lib/env/client";
import { getAccessToken } from "./access-token";
import { toApiError } from "./errors";
import { refreshAccessToken } from "./refresh";

export type ApiClientOptions = {
  baseUrl?: string;
  getAccessToken?: () => string | undefined | Promise<string | undefined>;
  onUnauthorized?: () => void | Promise<void>;
};

function isAuthenticationRequest(url: string) {
  return new URL(url).pathname.startsWith("/api/v1/auth/");
}

export async function authenticatedFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
) {
  const request = new Request(input, init);
  const token = getAccessToken();
  if (token) request.headers.set("Authorization", `Bearer ${token}`);
  const retryTemplate = request.clone();
  const response = await fetch(request);

  if (response.status !== 401 || isAuthenticationRequest(request.url)) {
    return response;
  }

  const refreshedToken = await refreshAccessToken();
  const retry = new Request(retryTemplate);
  retry.headers.set("Authorization", `Bearer ${refreshedToken}`);
  return fetch(retry);
}

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

export const publicApiClient = createApiClient();

export const apiClient = createClient<paths>({
  baseUrl: clientEnvironment.NEXT_PUBLIC_API_URL,
  credentials: "include",
  fetch: authenticatedFetch,
});

apiClient.use({
  async onResponse({ response }) {
    if (!response.ok) throw await toApiError(response);
    return response;
  },
});
