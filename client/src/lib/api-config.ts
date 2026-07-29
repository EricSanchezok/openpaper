export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL
    ?? (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "");

export const API_V1_PREFIX = "/api/v1";

export function apiUrl(endpoint: string): string {
    if (!endpoint.startsWith("/") || endpoint.startsWith("/api/")) {
        throw new Error(`API endpoint must be an unversioned resource path: ${endpoint}`);
    }
    return `${API_BASE_URL}${API_V1_PREFIX}${endpoint}`;
}
