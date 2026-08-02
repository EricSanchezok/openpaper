"use client";

import { useTranslations } from "next-intl";

import { AsyncFeedback } from "@/components/feedback/async-feedback";

export default function ErrorPage({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const common = useTranslations("Common");
  const errorMessage = useTranslations("Errors.unexpected");

  return (
    <main className="grid min-h-screen place-items-center p-6">
      <AsyncFeedback
        action={{ label: common("actions.tryAgain"), onClick: reset }}
        description={errorMessage("description")}
        presentation="block"
        state="error"
        title={errorMessage("title")}
      />
    </main>
  );
}
