'use client';

import { useEffect } from 'react';
import { reportClientError } from '@/lib/client-observability';

export default function GlobalError({
    error,
    reset,
}: {
    error: Error & { digest?: string };
    reset: () => void;
}) {
    useEffect(() => {
        reportClientError(error, { boundary: 'global' });
    }, [error]);

    return (
        <html lang="en">
            <body>
                <main style={{ maxWidth: 560, margin: '15vh auto', padding: 24, textAlign: 'center' }}>
                    <h1>Scholens encountered an unexpected error</h1>
                    <p>The failure has been recorded. Please retry this page.</p>
                    {error.digest ? <p>Diagnostic ID: {error.digest}</p> : null}
                    <button type="button" onClick={reset}>Try again</button>
                </main>
            </body>
        </html>
    );
}
