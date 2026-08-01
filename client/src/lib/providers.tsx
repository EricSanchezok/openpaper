// app/providers.tsx
'use client'

import { usePathname, useSearchParams } from "next/navigation"
import { useEffect, Suspense } from "react"
import { usePostHog } from 'posthog-js/react'

import posthog from 'posthog-js'
import { PostHogProvider as PHProvider } from 'posthog-js/react'
import { useIsDarkMode } from "@/hooks/useDarkMode"
import { initializeClientObservability, reportClientError } from '@/lib/client-observability'

// Note: This provider does not work wherever adblock is enabled.
export function PostHogProvider({ children }: { children: React.ReactNode }) {
    useEffect(() => {
        initializeClientObservability();
        const onError = (event: ErrorEvent) => {
            reportClientError(event.error ?? new Error(event.message), {
                boundary: 'window',
            });
        };
        const onUnhandledRejection = (event: PromiseRejectionEvent) => {
            reportClientError(event.reason, { boundary: 'unhandled_rejection' });
        };
        window.addEventListener('error', onError);
        window.addEventListener('unhandledrejection', onUnhandledRejection);

        const key = process.env.NEXT_PUBLIC_POSTHOG_KEY;
        if (key) {
            posthog.init(key, {
                api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST || 'https://us.i.posthog.com',
                person_profiles: 'identified_only',
                capture_pageview: false,
            });
        }
        return () => {
            window.removeEventListener('error', onError);
            window.removeEventListener('unhandledrejection', onUnhandledRejection);
        };
    }, [])

    return (
        <PHProvider client={posthog}>
            <SuspendedPostHogPageView />
            {children}
        </PHProvider>
    )
}

function PostHogPageView() {
    const pathname = usePathname()
    const searchParams = useSearchParams()
    const posthog = usePostHog()

    // Track pageviews
    useEffect(() => {
        if (pathname && posthog) {
            let url = window.origin + pathname
            if (searchParams.toString()) {
                url = url + "?" + searchParams.toString();
            }

            posthog.capture('$pageview', { '$current_url': url })
        }
    }, [pathname, searchParams, posthog])

    return null
}

// Wrap PostHogPageView in Suspense to avoid the useSearchParams usage above
// from de-opting the whole app into client-side rendering
// See: https://nextjs.org/docs/messages/deopted-into-client-rendering
function SuspendedPostHogPageView() {
    return (
        <Suspense fallback={null}>
            <PostHogPageView />
        </Suspense>
    )
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
    // Actually use the hook - this ensures React is aware of the dark mode state
    const {  } = useIsDarkMode();

    return <>{children}</>;
}
