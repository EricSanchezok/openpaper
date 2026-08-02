import type { Preview } from "@storybook/nextjs-vite";
import { getWorker, initialize, mswLoader } from "msw-storybook-addon";
import { useEffect } from "react";

import { QueryProvider } from "../src/lib/query/query-provider";
import { foundationHandler } from "./msw/handlers";
import "../src/styles/globals.css";

initialize({ onUnhandledRequest: "bypass" });

const preview: Preview = {
  decorators: [
    (Story, context) => {
      const appearance =
        context.globals.appearance === "dark" ? "dark" : "light";
      useEffect(() => {
        document.documentElement.dataset.theme = "default";
        document.documentElement.dataset.colorScheme = appearance;
        document.documentElement.lang = String(context.globals.locale ?? "en");
      }, [appearance, context.globals.locale]);
      return (
        <QueryProvider>
          <div className="bg-canvas text-foreground min-h-screen p-6">
            <Story />
          </div>
        </QueryProvider>
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
          { value: "zh-TW", title: "繁體中文" },
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
  loaders: [
    mswLoader,
    async (context) => {
      const worker = getWorker();
      worker.resetHandlers();
      worker.use(
        foundationHandler({
          network:
            context.globals.network === "slow" ||
            context.globals.network === "offline"
              ? context.globals.network
              : "instant",
          data:
            context.globals.data === "empty" || context.globals.data === "error"
              ? context.globals.data
              : "populated",
        }),
      );
      return {};
    },
  ],
  parameters: {
    a11y: { test: "error" },
    controls: { expanded: true },
    layout: "fullscreen",
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
      },
    },
  },
};

export default preview;
