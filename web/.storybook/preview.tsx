import type { Preview } from "@storybook/nextjs-vite";
import { initialize, mswLoader } from "msw-storybook-addon";
import { NextIntlClientProvider } from "next-intl";
import { useEffect } from "react";

import { localeDirection, type AppLocale } from "../src/i18n/config";
import { formats } from "../src/i18n/formats";
import en from "../src/i18n/messages/en.json";
import zhCN from "../src/i18n/messages/zh-CN.json";
import { QueryProvider } from "../src/lib/query/query-provider";
import { foundationHandler } from "./msw/handlers";
import "../src/styles/globals.css";

initialize({ onUnhandledRequest: "error" });

const messages = { en, "zh-CN": zhCN } as const;

const preview: Preview = {
  decorators: [
    (Story, context) => {
      const appearance =
        context.globals.appearance === "dark" ? "dark" : "light";
      const locale: AppLocale =
        context.globals.locale === "zh-CN" ? "zh-CN" : "en";
      useEffect(() => {
        document.documentElement.dataset.theme = "default";
        document.documentElement.dataset.colorScheme = appearance;
        document.documentElement.lang = locale;
        document.documentElement.dir = localeDirection(locale);
      }, [appearance, locale]);
      return (
        <NextIntlClientProvider
          formats={formats}
          locale={locale}
          messages={messages[locale]}
          now={new Date("2026-08-04T10:00:00Z")}
          timeZone="UTC"
        >
          <QueryProvider>
            <div
              className={`bg-canvas text-foreground min-h-screen ${
                context.parameters.layout === "fullscreen" ? "" : "p-6"
              }`}
            >
              <Story />
            </div>
          </QueryProvider>
        </NextIntlClientProvider>
      );
    },
  ],
  globalTypes: {
    theme: {
      description: "Theme palette",
      defaultValue: "default",
      toolbar: {
        icon: "paintbrush",
        items: [{ value: "default", title: "Default" }],
      },
    },
    appearance: {
      description: "Color scheme",
      defaultValue: "light",
      toolbar: {
        icon: "mirror",
        items: [
          { value: "light", title: "Light" },
          { value: "dark", title: "Dark" },
        ],
      },
    },
    locale: {
      description: "Locale",
      defaultValue: "en",
      toolbar: {
        icon: "globe",
        items: [
          { value: "en", title: "English" },
          { value: "zh-CN", title: "简体中文" },
        ],
      },
    },
    network: {
      description: "Mock network",
      defaultValue: "instant",
      toolbar: {
        icon: "transfer",
        items: [
          { value: "instant", title: "Instant" },
          { value: "slow", title: "Slow" },
          { value: "offline", title: "Offline" },
        ],
      },
    },
    data: {
      description: "Mock data",
      defaultValue: "populated",
      toolbar: {
        icon: "database",
        items: [
          { value: "populated", title: "Populated" },
          { value: "empty", title: "Empty" },
          { value: "error", title: "Error" },
        ],
      },
    },
  },
  initialGlobals: {
    theme: "default",
    appearance: "light",
    locale: "en",
    network: "instant",
    data: "populated",
  },
  loaders: [mswLoader],
  parameters: {
    a11y: { test: "error" },
    controls: { expanded: true },
    layout: "fullscreen",
    msw: { handlers: [foundationHandler] },
    viewport: {
      options: {
        desktop: {
          name: "Desktop",
          styles: { width: "1440px", height: "900px" },
        },
        narrowPanel: {
          name: "Narrow panel",
          styles: { width: "480px", height: "900px" },
        },
        mobile: { name: "Mobile", styles: { width: "390px", height: "844px" } },
        smallMobile: {
          name: "Small Mobile",
          styles: { width: "320px", height: "568px" },
        },
        tablet: {
          name: "Tablet",
          styles: { width: "768px", height: "1024px" },
        },
      },
    },
  },
};

export default preview;
