type ErrorContext = Record<string, string | number | boolean | undefined>;

interface RumClient {
    recordError(error: Error): void;
    recordEvent?(type: string, data: Record<string, unknown>): void;
}

declare global {
    interface Window {
        __SCHOLENS_RUM__?: RumClient;
    }
}

export function reportClientError(
    error: unknown,
    context: ErrorContext = {},
): void {
    const normalized = error instanceof Error ? error : new Error(String(error));
    if (typeof window === 'undefined') return;
    window.__SCHOLENS_RUM__?.recordError(normalized);
    window.__SCHOLENS_RUM__?.recordEvent?.('scholens_client_error', {
        error_name: normalized.name,
        ...context,
    });
}
