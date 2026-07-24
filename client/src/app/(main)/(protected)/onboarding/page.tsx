"use client";

import { ScholensOnboarding } from "@/components/ScholensOnboarding";

export default function OnboardingPage() {
    return (
        <div className="flex min-h-[calc(100vh-64px)] flex-col items-center p-4 md:pt-16">
            <div className="w-full max-w-2xl">
                <h1 className="mb-4 text-center text-2xl font-bold">Welcome to Scholens</h1>
                <p className="mb-8 text-muted-foreground">
                    A few details help us tailor your paper-reading and knowledge-base experience.
                </p>
                <ScholensOnboarding />
            </div>
        </div>
    );
}
