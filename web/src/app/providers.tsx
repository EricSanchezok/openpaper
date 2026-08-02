"use client";

import { ThemeProvider } from "@/design-system/theme/theme-provider";
import { ToastProvider } from "@/components/ui/toast";
import { QueryProvider } from "@/lib/query/query-provider";
import { useTranslations } from "next-intl";

export function Providers({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const t = useTranslations("Common.actions");
  return (
    <ThemeProvider>
      <QueryProvider>
        <ToastProvider dismissLabel={t("dismiss")}>{children}</ToastProvider>
      </QueryProvider>
    </ThemeProvider>
  );
}
