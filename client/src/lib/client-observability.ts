import { AwsRum, PageIdFormatEnum } from 'aws-rum-web';

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

let rumInitialized = false;
const reportedErrors = new WeakSet<Error>();

export function initializeClientObservability(): void {
    if (typeof window === 'undefined' || rumInitialized) return;
    rumInitialized = true;
    const applicationId = process.env.NEXT_PUBLIC_RUM_APPLICATION_ID;
    const guestRoleArn = process.env.NEXT_PUBLIC_RUM_GUEST_ROLE_ARN;
    const identityPoolId = process.env.NEXT_PUBLIC_RUM_IDENTITY_POOL_ID;
    const region = process.env.NEXT_PUBLIC_RUM_REGION;
    if (!applicationId || !guestRoleArn || !identityPoolId || !region) return;
    const releaseId = process.env.NEXT_PUBLIC_RELEASE_SHA || 'development';
    try {
        window.__SCHOLENS_RUM__ = new AwsRum(
            applicationId,
            releaseId,
            region,
            {
                allowCookies: false,
                enableXRay: true,
                guestRoleArn,
                identityPoolId,
                pageIdFormat: PageIdFormatEnum.Path,
                sessionSampleRate: 1,
                telemetries: [
                    'errors',
                    'performance',
                    [
                        'http',
                        {
                            // RUM records request URLs verbatim. Requests with a
                            // query or fragment stay observable through the
                            // shared ApiError reporter without exporting the URL.
                            urlsToInclude: [/^[^?#]+$/],
                        },
                    ],
                ],
                recordResourceUrl: false,
                releaseId,
            },
        );
    } catch {
        // Observability is fail-open and must never prevent the application boot.
        window.__SCHOLENS_RUM__ = undefined;
    }
}

export function reportClientError(
    error: unknown,
    context: ErrorContext = {},
): void {
    const normalized = error instanceof Error
        ? error
        : new Error('Non-Error client failure');
    if (typeof window === 'undefined') return;
    if (reportedErrors.has(normalized)) return;
    reportedErrors.add(normalized);
    window.__SCHOLENS_RUM__?.recordError(normalized);
    window.__SCHOLENS_RUM__?.recordEvent?.('scholens_client_error', {
        error_name: normalized.name,
        ...context,
    });
}

/** Report a caught UI failure without leaking arbitrary console arguments. */
export function reportClientIssue(...values: unknown[]): void {
    const error = values.find((value): value is Error => value instanceof Error);
    reportClientError(error ?? new Error('Client operation failed'), {
        boundary: 'caught_client_error',
    });
}
