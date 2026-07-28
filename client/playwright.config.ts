import { defineConfig, devices } from "@playwright/test";

const port = 3100;

export default defineConfig({
	testDir: "./tests/e2e",
	fullyParallel: true,
	timeout: 120_000,
	expect: { timeout: 30_000 },
	retries: process.env.CI ? 2 : 0,
	reporter: process.env.CI ? "github" : "list",
	use: {
		baseURL: `http://127.0.0.1:${port}`,
		trace: "retain-on-failure",
	},
	projects: [
		{ name: "chromium", use: { ...devices["Desktop Chrome"] } },
		{
			name: "mobile",
			use: { ...devices["iPhone 13"], browserName: "chromium" },
		},
	],
	webServer: {
		command: `NEXT_PUBLIC_API_URL=http://127.0.0.1:${port} npm run build && HOSTNAME=127.0.0.1 PORT=${port} npm run start:standalone`,
		url: `http://127.0.0.1:${port}`,
		reuseExistingServer: false,
		timeout: 120_000,
	},
});
