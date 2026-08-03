import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const apiPattern = "**/api/v1";

async function mockAnonymousSession(page: Page) {
  await page.route(`${apiPattern}/auth/refresh`, async (route) => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({
        code: "auth_session_missing",
        message: "session missing",
      }),
    });
  });
}

test.beforeEach(async ({ page }) => {
  await mockAnonymousSession(page);
});

test("renders the sign-in entry accessibly and normalizes an invalid mode", async ({
  page,
}) => {
  await page.goto("/login?mode=not-a-real-mode");
  await expect(
    page.getByRole("heading", { name: "Welcome back" }),
  ).toBeVisible();
  await expect(page.getByLabel("Email")).toHaveAttribute(
    "autocomplete",
    "email",
  );
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test("does not call action endpoints when a verify or reset token is missing", async ({
  page,
}) => {
  let actionRequests = 0;
  await page.route(`${apiPattern}/auth/verify-email`, async (route) => {
    actionRequests += 1;
    await route.fulfill({ status: 204 });
  });
  await page.route(`${apiPattern}/auth/reset-password`, async (route) => {
    actionRequests += 1;
    await route.fulfill({ status: 204 });
  });

  await page.goto("/login?mode=verify");
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "This link has expired",
    }),
  ).toBeVisible();
  await page.goto("/login?mode=reset");
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "This link has expired",
    }),
  ).toBeVisible();
  expect(actionRequests).toBe(0);
});

test("submits registration without confirmPassword and shows a generic result", async ({
  page,
}) => {
  let requestBody: Record<string, unknown> | undefined;
  await page.route(`${apiPattern}/auth/register`, async (route) => {
    requestBody = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ message: "ok" }),
    });
  });
  await page.goto("/login?mode=register");
  await page.getByLabel("Name").fill("Eric");
  await page.getByLabel("Email").fill("eric@example.com");
  await page.getByLabel("Password", { exact: true }).fill("twelve-chars!");
  await page.getByLabel("Confirm password").fill("twelve-chars!");
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(
    page.getByRole("heading", { name: "Check your inbox" }).first(),
  ).toBeVisible();
  expect(requestBody).toMatchObject({
    display_name: "Eric",
    email: "eric@example.com",
    password: "twelve-chars!",
  });
  expect(requestBody).not.toHaveProperty("confirmPassword");
  expect(
    await page.evaluate(() => ({
      local: Object.keys(localStorage).filter((key) =>
        key.startsWith("scholens."),
      ),
      session: Object.keys(sessionStorage).filter((key) =>
        key.startsWith("scholens."),
      ),
    })),
  ).toEqual({
    local: [],
    session: ["scholens.pending-verification-email"],
  });
});

test("preserves only a safe returnTo when switching modes", async ({
  page,
}) => {
  await page.goto("/login?returnTo=%2Flibrary%3Fview%3Drecent");
  await expect(
    page.getByRole("link", { name: "Create account" }),
  ).toHaveAttribute(
    "href",
    "/login?mode=register&returnTo=%2Flibrary%3Fview%3Drecent",
  );

  await page.goto("/login?returnTo=https%3A%2F%2Fevil.example%2Fsteal");
  await expect(
    page.getByRole("link", { name: "Create account" }),
  ).toHaveAttribute("href", "/login?mode=register");
});

test("fits a 320px viewport without horizontal scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto("/login?mode=register");
  await expect(
    page.getByRole("heading", { name: "Create your account" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("uses the Simplified Chinese authentication dictionary", async ({
  context,
  page,
}) => {
  await context.addCookies([
    {
      name: "scholens-locale",
      value: "zh-CN",
      domain: "localhost",
      path: "/",
    },
  ]);
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "欢迎回来" })).toBeVisible();
});
