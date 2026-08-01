export type FailureKind =
    | "invalid_argument"
    | "unauthenticated"
    | "permission_denied"
    | "not_found"
    | "conflict"
    | "payload_too_large"
    | "unprocessable"
    | "rate_limited"
    | "dependency_failure"
    | "unavailable"
    | "internal";

export interface ErrorEnvelope {
    code: string;
    message: string;
    kind: FailureKind;
    retryable: boolean;
    stage?: string;
    request_id?: string;
    correlation_id?: string;
    diagnostic_id?: string;
    details?: Record<string, unknown>;
}

export class ApiError extends Error {
    readonly status: number;
    readonly envelope: ErrorEnvelope;

    constructor(status: number, envelope: ErrorEnvelope) {
        super(envelope.message);
        this.name = "ApiError";
        this.status = status;
        this.envelope = envelope;
    }

    get retryable(): boolean {
        return this.envelope.retryable;
    }

    get diagnosticId(): string | undefined {
        return this.envelope.diagnostic_id ?? this.envelope.request_id;
    }
}

const FAILURE_KINDS = new Set<FailureKind>([
    "invalid_argument",
    "unauthenticated",
    "permission_denied",
    "not_found",
    "conflict",
    "payload_too_large",
    "unprocessable",
    "rate_limited",
    "dependency_failure",
    "unavailable",
    "internal",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseErrorEnvelope(
    value: unknown,
    fallback: { status: number; requestId?: string; statusText?: string },
): ErrorEnvelope {
    const record = isRecord(value) && isRecord(value.error) ? value.error : value;
    if (isRecord(record)) {
        const kind = FAILURE_KINDS.has(record.kind as FailureKind)
            ? (record.kind as FailureKind)
            : fallback.status === 401
              ? "unauthenticated"
              : fallback.status === 403
                ? "permission_denied"
                : fallback.status >= 500
                  ? "internal"
                  : "invalid_argument";
        return {
            code: typeof record.code === "string" ? record.code : "request_failed",
            message:
                typeof record.message === "string"
                    ? record.message
                    : `Request failed (${fallback.status}${fallback.statusText ? ` ${fallback.statusText}` : ""})`,
            kind,
            retryable:
                typeof record.retryable === "boolean"
                    ? record.retryable
                    : kind === "rate_limited" || kind === "dependency_failure" || kind === "unavailable",
            stage: typeof record.stage === "string" ? record.stage : undefined,
            request_id:
                typeof record.request_id === "string"
                    ? record.request_id
                    : fallback.requestId,
            correlation_id:
                typeof record.correlation_id === "string"
                    ? record.correlation_id
                    : undefined,
            diagnostic_id:
                typeof record.diagnostic_id === "string"
                    ? record.diagnostic_id
                    : undefined,
            details: isRecord(record.details) ? record.details : undefined,
        };
    }
    return {
        code: "request_failed",
        message: `Request failed (${fallback.status}${fallback.statusText ? ` ${fallback.statusText}` : ""})`,
        kind: fallback.status >= 500 ? "internal" : "invalid_argument",
        retryable: fallback.status >= 500,
        request_id: fallback.requestId,
    };
}

export async function apiErrorFromResponse(response: Response): Promise<ApiError> {
    let payload: unknown;
    try {
        payload = await response.json();
    } catch {
        payload = undefined;
    }
    return new ApiError(
        response.status,
        parseErrorEnvelope(payload, {
            status: response.status,
            statusText: response.statusText,
            requestId: response.headers.get("X-Request-ID") ?? undefined,
        }),
    );
}

export function errorMessageWithDiagnostic(error: unknown): string {
    if (!(error instanceof ApiError)) {
        return error instanceof Error ? error.message : "An unexpected error occurred.";
    }
    const diagnostic = error.diagnosticId;
    return diagnostic
        ? `${error.message} Diagnostic ID: ${diagnostic}`
        : error.message;
}
