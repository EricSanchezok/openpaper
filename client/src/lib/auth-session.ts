const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL
    ?? (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "");

export const REFRESH_TOKEN_KEY = "openpaper.refresh_token";
const REFRESH_LOCK = "openpaper-auth-refresh";
const CHANNEL_NAME = "openpaper-auth";

export interface TokenResponse {
    access_token: string;
    refresh_token: string;
    token_type: string;
}

let accessToken: string | null = null;
let refreshFlight: Promise<string> | null = null;
const localListeners = new Set<() => void>();
const channel = typeof BroadcastChannel === "undefined"
    ? null
    : new BroadcastChannel(CHANNEL_NAME);

export function getAccessToken(): string | null {
    return accessToken;
}

export function hasRefreshToken(): boolean {
    return typeof window !== "undefined" && Boolean(localStorage.getItem(REFRESH_TOKEN_KEY));
}

export function establishSession(tokens: TokenResponse, announce = true): void {
    accessToken = tokens.access_token;
    localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token);
    if (announce) channel?.postMessage({ type: "session-changed" });
}

export function clearSession(announce = true): void {
    accessToken = null;
    if (typeof window !== "undefined") localStorage.removeItem(REFRESH_TOKEN_KEY);
    if (announce) {
        localListeners.forEach((listener) => listener());
        channel?.postMessage({ type: "signed-out" });
    }
}

async function rotateRefreshToken(): Promise<string> {
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
    if (!refreshToken) throw new Error("No refresh token is available");

    const response = await fetch(`${API_BASE_URL}/api/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!response.ok) {
        if ([400, 401, 404].includes(response.status)) clearSession();
        throw new Error("Unable to refresh session");
    }

    const tokens = (await response.json()) as TokenResponse;
    establishSession(tokens, false);
    return tokens.access_token;
}

export function refreshAccessToken(): Promise<string> {
    if (refreshFlight) return refreshFlight;

    const run = async () => {
        if (navigator.locks) return navigator.locks.request(REFRESH_LOCK, rotateRefreshToken);
        return rotateRefreshToken();
    };
    refreshFlight = run().finally(() => {
        refreshFlight = null;
    });
    return refreshFlight;
}

export function subscribeToSessionChanges(listener: () => void): () => void {
    localListeners.add(listener);
    const storageListener = (event: StorageEvent) => {
        if (
            event.key === REFRESH_TOKEN_KEY
            && (event.oldValue === null || event.newValue === null)
        ) listener();
    };
    const channelListener = () => listener();
    window.addEventListener("storage", storageListener);
    channel?.addEventListener("message", channelListener);
    return () => {
        localListeners.delete(listener);
        window.removeEventListener("storage", storageListener);
        channel?.removeEventListener("message", channelListener);
    };
}
