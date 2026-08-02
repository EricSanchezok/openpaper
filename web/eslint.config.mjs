import { defineConfig, globalIgnores } from "eslint/config";
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypeScript from "eslint-config-next/typescript";
import storybook from "eslint-plugin-storybook";

export default defineConfig([
  ...nextCoreWebVitals,
  ...nextTypeScript,
  ...storybook.configs["flat/recommended"],
  globalIgnores([
    ".next/**",
    "storybook-static/**",
    "public/mockServiceWorker.js",
    "src/design-system/generated/**",
    "src/lib/api/generated/**",
  ]),
]);
