import type { Metadata } from "next";

import { Providers } from "@/app/providers";
import { themeInitializationScript } from "@/design-system/theme/theme-script";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: "Scholens Web Foundation",
  description: "Scholens next-generation web foundation smoke test",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      data-color-scheme="light"
      data-theme="default"
      lang="en"
      suppressHydrationWarning
    >
      <head>
        <script
          dangerouslySetInnerHTML={{ __html: themeInitializationScript }}
        />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
