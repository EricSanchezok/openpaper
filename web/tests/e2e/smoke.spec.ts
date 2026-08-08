import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import {
  homeConversations,
  homeMessages,
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

test("renders an intentional first-run Home without empty card shells", async ({
  page,
}) => {
  await page.unroute(`${apiPattern}/conversations**`);
  await page.unroute(`${apiPattern}/library/papers`);
  await page.unroute(`${apiPattern}/projects**`);
  await page.route(`${apiPattern}/conversations**`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [], next_cursor: null }),
    }),
  );
  await page.route(`${apiPattern}/library/papers`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [], next_cursor: null }),
    }),
  );
  await page.route(`${apiPattern}/projects**`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [], next_cursor: null }),
    }),
  );

  await page.goto("/");
  await expect(page.getByText(/Ask across a paper/)).toBeVisible();
  await expect(page.getByText("Recent papers", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Recent projects", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByText("Your conversations will appear here."),
  ).toBeVisible();

  const composer = page.getByRole("textbox", { name: "Ask anything" });
  const submit = page.getByRole("button", { name: "Ask Scholens" });
  await composer.click();
  await expect
    .poll(() =>
      composer.evaluate((element) => getComputedStyle(element).outlineStyle),
    )
    .toBe("none");
  await expect
    .poll(() =>
      submit.evaluate((element) => {
        const icon = element.querySelector("svg");
        return icon
          ? getComputedStyle(icon).color === getComputedStyle(element).color
          : false;
      }),
    )
    .toBe(true);
});

test("lets the Server generate the initial conversation title", async ({
  page,
}) => {
  await page.goto("/");
  const creation = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/conversations"),
  );

  await page.getByRole("textbox", { name: "Ask anything" }).fill("Study RAG");
  await page.getByRole("button", { name: "Ask Scholens" }).click();

  expect((await creation).postDataJSON()).toEqual({
    scope_type: "global",
    paper_context: { kind: "library" },
  });
});

test("opens the context picker and changes its searchable selection", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Research scope: Library" }).click();
  await expect(
    page.getByRole("heading", { name: "Add context" }),
  ).toBeVisible();
  await page.getByRole("switch", { name: "Entire library" }).click();
  await page.getByRole("searchbox").fill("RAG");
  await expect(
    page.getByRole("checkbox", { name: /RAG evaluation/ }),
  ).toBeVisible();
});

test("keeps sidebar controls vertically anchored while collapsing", async ({
  page,
}) => {
  await page.goto("/");
  const collapse = page.getByRole("button", { name: "Collapse sidebar" });
  const newChat = page.getByRole("link", { name: "New chat" });
  const account = page.getByRole("button", { name: "Open account menu" });
  await expect(account.locator("svg")).toHaveCount(0);
  const before = {
    newChat: await newChat.evaluate((element) =>
      element.getBoundingClientRect().toJSON(),
    ),
    account: await account.evaluate((element) =>
      element.getBoundingClientRect().toJSON(),
    ),
  };

  await collapse.click();
  await expect(
    page.getByRole("button", { name: "Expand sidebar" }),
  ).toBeVisible();
  await expect(page.locator("aside")).toHaveCSS("width", "72px");
  const after = {
    newChat: await newChat.evaluate((element) =>
      element.getBoundingClientRect().toJSON(),
    ),
    account: await account.evaluate((element) =>
      element.getBoundingClientRect().toJSON(),
    ),
  };

  expect(Math.abs(after.newChat.y - before.newChat.y)).toBeLessThan(1);
  expect(Math.abs(after.account.y - before.account.y)).toBeLessThan(1);
});

test("fits the Home shell at 390px without horizontal scrolling", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open navigation" }),
  ).toBeVisible();
  const primaryNavigation = page.getByRole("navigation", {
    name: "Primary navigation",
  });
  const activeDestination = primaryNavigation.getByRole("link", {
    name: "Ask",
  });
  await expect(activeDestination).toHaveAttribute("aria-current", "page");
  await expect(
    activeDestination.locator("[data-selected-indicator]"),
  ).toBeVisible();
  await expect(
    primaryNavigation.getByRole("button", {
      name: "Library. Not available yet",
    }),
  ).toBeDisabled();
  const dock = page.getByTestId("mobile-bottom-dock");
  await expect(dock.getByRole("textbox", { name: "Ask anything" })).toHaveCount(
    1,
  );
  await expect(dock.getByRole("navigation")).toHaveCount(1);
  await expect(
    dock.getByRole("button", { name: "Research scope: Library" }),
  ).toBeVisible();
  const touchTargets = dock.locator("button:visible, a:visible");
  for (let index = 0; index < (await touchTargets.count()); index += 1) {
    const box = await touchTargets.nth(index).boundingBox();
    expect(box?.height).toBeGreaterThanOrEqual(48);
    expect(box?.width).toBeGreaterThanOrEqual(48);
  }

  await page
    .getByRole("button", { name: "Reasoning strength: Standard" })
    .click();
  await expect(page.getByRole("menuitemradio")).toHaveCount(2);
  await expect(
    page.getByRole("menuitemradio", { name: /Standard/ }),
  ).toBeVisible();
  await expect(page.getByText("Choose model")).toHaveCount(0);
  await page.getByRole("menuitemradio", { name: /Deep/ }).click();
  await expect(
    page.getByRole("button", { name: "Reasoning strength: Deep" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Open navigation" }).click();
  const navigationHub = page.getByRole("dialog");
  await expect(
    navigationHub.getByRole("searchbox", { name: "Search conversations" }),
  ).toBeVisible();
  await expect(
    navigationHub.getByRole("link", { name: "New chat" }),
  ).toHaveCount(0);
  await navigationHub.getByRole("button", { name: "Close navigation" }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("keeps the unified mobile Dock contained at 320px", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto("/");

  const dock = page.getByTestId("mobile-bottom-dock");
  const composer = dock.getByRole("textbox", { name: "Ask anything" });
  await expect(composer).toBeVisible();
  await expect(dock.getByTestId("mobile-tab-bar")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);

  const [dockBox, composerBox] = await Promise.all([
    dock.boundingBox(),
    composer.boundingBox(),
  ]);
  expect(dockBox?.y).toBeGreaterThan(0);
  expect(composerBox?.y).toBeGreaterThanOrEqual(dockBox?.y ?? 0);
});

test("keeps conversation scrolling independent from the mobile Dock", async ({
  page,
}) => {
  const conversation = homeConversations[0]!;
  const messages = Array.from({ length: 6 }).flatMap((_, index) =>
    homeMessages.map((message) => ({
      ...message,
      id: `${message.id.slice(0, -1)}${index}`,
      turn_id: `${message.turn_id.slice(0, -1)}${index}`,
      sequence: message.sequence + index * 2,
    })),
  );
  await page.route(`${apiPattern}/conversations/${conversation.id}`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ...conversation,
        paper_context: { kind: "library" },
        tool_permissions: [],
      }),
    }),
  );
  await page.route(
    `${apiPattern}/conversations/${conversation.id}/messages**`,
    (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ items: messages, next_cursor: null }),
      }),
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/?conversation=${conversation.id}`);

  const main = page.locator("main");
  const dock = page.getByTestId("mobile-bottom-dock");
  await expect(
    page.getByRole("textbox", { name: "Ask a follow-up" }),
  ).toBeVisible();
  const dockBefore = await dock.boundingBox();
  expect(
    await main.evaluate(
      (element) => element.scrollHeight > element.clientHeight,
    ),
  ).toBe(true);
  await main.evaluate((element) => element.scrollTo({ top: 240 }));
  const [dockAfter, mainAfter] = await Promise.all([
    dock.boundingBox(),
    main.boundingBox(),
  ]);
  expect(dockAfter?.y).toBe(dockBefore?.y);
  expect((mainAfter?.y ?? 0) + (mainAfter?.height ?? 0)).toBeLessThanOrEqual(
    dockAfter?.y ?? 0,
  );
});

test("keeps the Home composition contained on a 2560px desktop", async ({
  page,
}) => {
  await page.setViewportSize({ width: 2560, height: 1440 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "What are you working on?" }),
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
