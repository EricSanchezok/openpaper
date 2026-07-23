const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL
    ?? (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "");

const REFRESH_LOCK = "openpaper-auth-refresh";
const CHANNEL_NAME = "openpaper-auth";

export interface TokenResponse {
    access_token: string;
    token_type: string;
}

export type SessionEvent = "session-changed" | "signed-out";

let accessToken: string | null = null;
let refreshFlight: Promise<string> | null = null;
const localListeners = new Set<(event: SessionEvent) => void>();
const channel = typeof window === "undefined" || typeof BroadcastChannel === "undefined"
    ? null
    : new BroadcastChannel(CHANNEL_NAME);

export function getAccessToken(): string | null {
    return accessToken;
}

export function establishSession(tokens: TokenResponse, announce = true): void {
    accessToken = tokens.access_token;
    if (announce) channel?.postMessage({ type: "session-changed" });
}

export function clearSession(announce = true): void {
    accessToken = null;
    if (announce) {
        localListeners.forEach((listener) => listener("signed-out"));
        channel?.postMessage({ type: "signed-out" });
    }
}

async function rotateRefreshToken(): Promise<string> {
    const response = await fetch(`${API_BASE_URL}/api/auth/refresh`, {
        method: "POST",
        credentials: "include",
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

export function subscribeToSessionChanges(
    listener: (event: SessionEvent) => void,
): () => void {
    localListeners.add(listener);
    const channelListener = (event: MessageEvent<{ type?: string }>) => {
        if (event.data.type === "session-changed" || event.data.type === "signed-out") {
            listener(event.data.type);
        }
    };
    channel?.addEventListener("message", channelListener);
    return () => {
        localListeners.delete(listener);
        channel?.removeEventListener("message", channelListener);
    };
}
