import { storybookTest } from "@storybook/addon-vitest/vitest-plugin";
import { playwright } from "@vitest/browser-playwright";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const directory = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  optimizeDeps: {
    include: [
      "@radix-ui/react-dropdown-menu",
      "@radix-ui/react-scroll-area",
      "@radix-ui/react-toast",
      "@radix-ui/react-visually-hidden",
      "openapi-fetch",
      "zod",
    ],
  },
  resolve: { alias: { "@": path.resolve(directory, "src") } },
  test: {
    projects: [
      {
        resolve: { alias: { "@": path.resolve(directory, "src") } },
        test: {
          name: "unit",
          environment: "jsdom",
          include: ["src/**/*.test.{ts,tsx}"],
          setupFiles: ["./vitest.unit.setup.ts"],
        },
      },
      {
        plugins: [
          storybookTest({ configDir: path.join(directory, ".storybook") }),
        ],
        resolve: { alias: { "@": path.resolve(directory, "src") } },
        test: {
          name: "storybook",
          browser: {
            enabled: true,
            headless: true,
            provider: playwright({}),
            instances: [{ browser: "chromium" }],
          },
        },
      },
    ],
  },
});
