import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import {
  homeConversations,
  homePapers,
  homeProjects,
} from "../../src/features/home/api/fixtures";

const apiPattern = "**/api/v1";
const actor = {
  id: 7,
  email: "eric@scholens.ai",
  email_verified: true,
  is_active: true,
  is_admin: false,
  is_blocked: false,
  status: "active",
  display_name: "Eric",
  locale: "en",
};

async function mockHome(page: Page) {
  await page.route(`${apiPattern}/auth/refresh`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "playwright-access",
        token_type: "bearer",
      }),
    }),
  );
  await page.route(`${apiPattern}/me`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(actor),
    }),
  );
  await page.route(`${apiPattern}/conversations**`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: homeConversations, next_cursor: null }),
    }),
  );
  await page.route(`${apiPattern}/library/papers`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: homePapers, next_cursor: null }),
    }),
  );
  await page.route(`${apiPattern}/projects**`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: homeProjects, next_cursor: null }),
    }),
  );
}

test.beforeEach(async ({ page }) => {
  await mockHome(page);
});

test("renders the authenticated Home shell and primary data", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "What are you working on?" }),
  ).toBeVisible();
  await expect(page.getByText("Attention Is All You Need")).toBeVisible();
  await expect(page.getByText("Thesis literature review")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "default");
  await expect(page.locator("html")).toHaveAttribute(
    "data-color-scheme",
    /light|dark/,
  );

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test("opens the context picker and changes its searchable selection", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Add context" }).click();
  await expect(
    page.getByRole("heading", { name: "Add context" }),
  ).toBeVisible();
  await page.getByRole("switch", { name: "Entire library" }).click();
  await page.getByRole("searchbox").fill("RAG");
  await expect(
    page.getByRole("checkbox", { name: /RAG evaluation/ }),
  ).toBeVisible();
});

test("fits the Home shell at 390px without horizontal scrolling", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open navigation" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("locale cookie selects the Home interface dictionary", async ({
  context,
  page,
}) => {
  await context.addCookies([
    {
      name: "scholens-locale",
      value: "zh-CN",
      url: "http://127.0.0.1:7300",
    },
  ]);
  await page.goto("/");

  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
  await expect(
    page.getByRole("heading", { name: "你正在研究什么？" }),
  ).toBeVisible();
});
