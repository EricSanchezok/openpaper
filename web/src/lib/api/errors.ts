export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly correlationId?: string,
    readonly details?: unknown,
    readonly retryAfterSeconds?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function parseRetryAfter(
  value: string | null,
  now = Date.now(),
): number | undefined {
  if (!value) return undefined;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.ceil(seconds);
  const date = Date.parse(value);
  if (Number.isNaN(date)) return undefined;
  return Math.max(0, Math.ceil((date - now) / 1_000));
}

export async function toApiError(response: Response): Promise<ApiError> {
  const correlationId =
    response.headers.get("x-correlation-id") ??
    response.headers.get("x-request-id") ??
    undefined;
  let body: unknown;
  try {
    body = await response.clone().json();
  } catch {
    body = undefined;
  }
  const record =
    body && typeof body === "object"
      ? (body as Record<string, unknown>)
      : undefined;
  return new ApiError(
    typeof record?.message === "string"
      ? record.message
      : typeof record?.detail === "string"
        ? record.detail
        : `Request failed with status ${response.status}`,
    response.status,
    typeof record?.code === "string" ? record.code : undefined,
    correlationId,
    body,
    parseRetryAfter(response.headers.get("retry-after")),
  );
}
