import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages, getTranslations } from "next-intl/server";

import { Providers } from "@/app/providers";
import { themeInitializationScript } from "@/design-system/theme/theme-script";
import { localeDirection, type AppLocale } from "@/i18n/config";
import { formats } from "@/i18n/formats";
import "@/styles/globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Metadata");
  return { title: t("title"), description: t("description") };
}

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const locale = (await getLocale()) as AppLocale;
  const messages = await getMessages();

  return (
    <html
      data-color-scheme="light"
      data-theme="default"
      dir={localeDirection(locale)}
      lang={locale}
      suppressHydrationWarning
    >
      <head>
        <script
          dangerouslySetInnerHTML={{ __html: themeInitializationScript }}
        />
      </head>
      <body>
        <NextIntlClientProvider
          formats={formats}
          locale={locale}
          messages={messages}
          timeZone="UTC"
        >
          <Providers>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
