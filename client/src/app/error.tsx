'use client';

import { useEffect } from 'react';
import { reportClientError } from '@/lib/client-observability';

export default function RouteError({
    error,
    reset,
}: {
    error: Error & { digest?: string };
    reset: () => void;
}) {
    useEffect(() => {
        reportClientError(error, { boundary: 'route' });
    }, [error]);

    return (
        <main className="flex min-h-[60vh] items-center justify-center p-8">
            <div className="max-w-lg space-y-4 text-center">
                <h1 className="text-xl font-semibold">This page could not be displayed</h1>
                <p className="text-sm text-muted-foreground">
                    The failure has been recorded. You can retry without losing your account data.
                </p>
                {error.digest ? (
                    <p className="font-mono text-xs text-muted-foreground">
                        Diagnostic ID: {error.digest}
                    </p>
                ) : null}
                <button
                    type="button"
                    className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground"
                    onClick={reset}
                >
                    Try again
                </button>
            </div>
        </main>
    );
}
