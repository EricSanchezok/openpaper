import {
    clearSession,
    getAccessToken,
    refreshAccessToken,
} from "./auth-session";
import { apiUrl } from "./api-config";
import { apiErrorFromResponse } from "./errors";
import type {
    AccessKeyCreateRequest,
    AccessKeyCreateResponse,
    AccessKeyListResponse,
    AccessKeyResponse,
    AccessKeyUpdateRequest,
    ConnectorListResponse,
    ConnectorProvider,
    ConnectorResponse,
    Project,
    ProjectListResponse,
} from "./schema";

async function requestWithAuth(endpoint: string, options: RequestInit): Promise<Response> {
    const token = getAccessToken();
    const headers = new Headers(options.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const response = await fetch(apiUrl(endpoint), {
        ...options,
        headers,
        credentials: "include",
    });

    if (response.status !== 401 || !token) return response;

    try {
        const refreshedToken = await refreshAccessToken();
        const retryHeaders = new Headers(options.headers);
        retryHeaders.set("Authorization", `Bearer ${refreshedToken}`);
        return fetch(apiUrl(endpoint), {
            ...options,
            headers: retryHeaders,
            credentials: "include",
        });
    } catch {
        clearSession();
        return response;
    }
}

export async function fetchFromApi<T = unknown>(
    endpoint: string,
    options: RequestInit = {},
): Promise<T> {
    const headers: HeadersInit = {};

    // Only set Content-Type to application/json if we're not sending FormData
    if (!(options.body instanceof FormData)) {
        headers['Content-Type'] = 'application/json';
    }

    const response = await requestWithAuth(endpoint, {
        ...options,
        headers: {
            ...headers,
            ...options.headers,
        },
    });

    if (!response.ok) {
        throw await apiErrorFromResponse(response);
    }

    if (response.status === 204) {
        return null as T;
    }

    return response.json() as Promise<T>;
}

export async function fetchStreamFromApi(
    endpoint: string,
    options: RequestInit = {}
): Promise<ReadableStream<Uint8Array>> {
    const response = await requestWithAuth(endpoint, {
        ...options,
        headers: {
            ...options.headers,
            // For SSE, we want text/event-stream instead of octet-stream
            Accept: 'text/event-stream',
        },
    });

    if (!response.ok) {
        throw await apiErrorFromResponse(response);
    }

    if (!response.body) {
        throw new Error('Response body is null');
    }

    return response.body;
}

export async function getProjectsForPaper(documentId: string): Promise<Project[]> {
    const response = await fetchFromApi<ProjectListResponse>(
        `/papers/${documentId}/projects`,
    );
    return response.items;
}

/**
 * Fetch a fresh presigned file URL for a single paper within a project.
 * Access is granted via project membership, so this works for collaborators
 * who don't own the paper. Use this instead of refetching the whole project
 * paper list just to refresh one URL.
 */
export async function getProjectPaperFileUrl(
    projectId: string,
    documentId: string,
): Promise<string | null> {
    const response = await fetchFromApi<{ file_url: string | null }>(
        `/projects/${projectId}/papers/${documentId}/download-url`,
    );
    return response?.file_url ?? null;
}

/**
 * Fetch a fresh presigned file URL for a single owned paper. The cheap path
 * for refreshing an expired URL — avoids the metadata enrichment and full
 * canonical document payload.
 */
export async function getPaperFileUrl(documentId: string): Promise<string | null> {
    const response = await fetchFromApi<{ file_url: string | null }>(`/papers/${documentId}/download-url`);
    return response?.file_url ?? null;
}

export async function listAccessKeys({
    limit = 20,
    cursor,
}: {
    limit?: number;
    cursor?: string | null;
} = {}): Promise<AccessKeyListResponse> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (cursor) {
        params.set("cursor", cursor);
    }
    return fetchFromApi<AccessKeyListResponse>(
        `/me/access-keys?${params.toString()}`,
    );
}

export async function createAccessKey(
    request: AccessKeyCreateRequest,
): Promise<AccessKeyCreateResponse> {
    return fetchFromApi<AccessKeyCreateResponse>("/me/access-keys", {
        method: "POST",
        body: JSON.stringify(request),
    });
}

export async function updateAccessKey(
    accessKeyId: string,
    request: AccessKeyUpdateRequest,
): Promise<AccessKeyResponse> {
    return fetchFromApi<AccessKeyResponse>(
        `/me/access-keys/${encodeURIComponent(accessKeyId)}`,
        {
            method: "PATCH",
            body: JSON.stringify(request),
        },
    );
}

export async function revokeAccessKey(accessKeyId: string): Promise<void> {
    await fetchFromApi<void>(
        `/me/access-keys/${encodeURIComponent(accessKeyId)}`,
        { method: "DELETE" },
    );
}

export async function listConnectors(): Promise<ConnectorListResponse> {
    return fetchFromApi<ConnectorListResponse>("/me/connectors");
}

export async function connectConnector(
    provider: ConnectorProvider,
    apiKey: string,
): Promise<ConnectorResponse> {
    return fetchFromApi<ConnectorResponse>(
        `/me/connectors/${encodeURIComponent(provider)}`,
        {
            method: "PUT",
            body: JSON.stringify({ api_key: apiKey }),
        },
    );
}

export async function updateConnector(
    provider: ConnectorProvider,
    enabled: boolean,
): Promise<ConnectorResponse> {
    return fetchFromApi<ConnectorResponse>(
        `/me/connectors/${encodeURIComponent(provider)}`,
        {
            method: "PATCH",
            body: JSON.stringify({ enabled }),
        },
    );
}

export async function disconnectConnector(
    provider: ConnectorProvider,
): Promise<void> {
    await fetchFromApi<void>(
        `/me/connectors/${encodeURIComponent(provider)}`,
        { method: "DELETE" },
    );
}
