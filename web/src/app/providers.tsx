"use client";

import { ThemeProvider } from "@/design-system/theme/theme-provider";
import { QueryProvider } from "@/lib/query/query-provider";

export function Providers({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <ThemeProvider>
      <QueryProvider>{children}</QueryProvider>
    </ThemeProvider>
  );
}
