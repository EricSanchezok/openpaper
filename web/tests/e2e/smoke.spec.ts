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
