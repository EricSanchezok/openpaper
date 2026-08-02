"use client";

import { AsyncFeedback } from "@/components/feedback/async-feedback";

export default function ErrorPage({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="grid min-h-screen place-items-center p-6">
      <AsyncFeedback
        action={{ label: "Try again", onClick: reset }}
        description="The web foundation encountered an unexpected error."
        presentation="block"
        state="error"
        title="Something went wrong"
      />
    </main>
  );
}
