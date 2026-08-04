import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("foundation smoke route initializes providers and theme", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Scholens" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "default");
  await expect(page.locator("html")).toHaveAttribute(
    "data-color-scheme",
    /light|dark/,
  );

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test("locale cookie selects the active interface dictionary", async ({
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
  await expect(page.getByText("前端基础 · 验证页面")).toBeVisible();
  await expect(
    page.getByRole("link", { name: /打开 Storybook/ }),
  ).toBeVisible();
});
