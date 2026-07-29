import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({
    baseDirectory: __dirname,
});

const eslintConfig = [
    {
        ignores: [".next/**", "node_modules/**", "public/**", "next-env.d.ts"],
    },
    ...compat.extends("next/core-web-vitals", "next/typescript"),
    {
        rules: {
            "react-hooks/exhaustive-deps": "off"
        }
    },
    {
        files: [
            "src/app/**/*.{ts,tsx}",
            "src/components/**/*.{ts,tsx}",
            "src/hooks/**/*.{ts,tsx}",
        ],
        rules: {
            "no-restricted-globals": [
                "error",
                {
                    name: "fetch",
                    message: "Use the typed API client; keep authentication and error handling centralized.",
                },
            ],
        },
    },
    {
        files: ["src/components/BlogPostToast.tsx"],
        rules: {
            // This reads a static file emitted by the Next.js build, not the API.
            "no-restricted-globals": "off",
        },
    }
];

export default eslintConfig;
