import {
    clearSession,
    getAccessToken,
    refreshAccessToken,
} from "./auth-session";
import { apiUrl } from "./api-config";

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

export async function fetchFromApi(endpoint: string, options: RequestInit = {}) {
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
        let errorMessage: unknown = `API error: ${response.status}`;

        try {
            const errorData = await response.json();
            if (errorData.message) {
                errorMessage = errorData.message;
            } else if (errorData.error) {
                errorMessage = errorData.error;
            } else if (errorData.detail) {
                errorMessage = errorData.detail;
            }
        } catch {
            // If we can't parse the error response, fall back to status text
            errorMessage = `API error: ${response.status} ${response.statusText}`;
        }

        if (typeof errorMessage !== 'string') {
            errorMessage = JSON.stringify(errorMessage);
        }

        throw new Error(errorMessage as string)
    }

    if (response.status === 204) {
        return null; // No content to return
    }

    return response.json();
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
        let errorMessage: unknown = `API error: ${response.status}`;

        try {
            const errorData = await response.json();
            if (errorData.message) {
                errorMessage = errorData.message;
            } else if (errorData.error) {
                errorMessage = errorData.error;
            } else if (errorData.detail) {
                errorMessage = errorData.detail;
            }
        } catch {
            // If we can't parse the error response, fall back to status text
            errorMessage = `API error: ${response.status} ${response.statusText}`;
        }

        if (typeof errorMessage !== 'string') {
            errorMessage = JSON.stringify(errorMessage);
        }

        throw new Error(errorMessage as string);
    }

    if (!response.body) {
        throw new Error('Response body is null');
    }

    return response.body;
}

export async function getProjectsForPaper(documentId: string) {
    return fetchFromApi(`/projects/papers/from/${documentId}`);
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
    const response = await fetchFromApi(
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
    const response = await fetchFromApi(`/papers/${documentId}/download-url`);
    return response?.file_url ?? null;
}
