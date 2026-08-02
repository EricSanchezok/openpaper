import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { expect, within } from "storybook/test";

function InternationalizationDemo() {
  const locale = useLocale();
  const t = useTranslations("I18nDemo");
  const format = useFormatter();
  const date = new Date("2026-08-02T00:00:00.000Z");

  return (
    <section className="border-line bg-surface grid max-w-xl gap-5 rounded-[var(--radius-lg)] border p-6">
      <div>
        <p className="text-muted text-sm">{locale}</p>
        <h1 className="mt-1 text-xl font-semibold">{t("title")}</h1>
      </div>
      <dl className="grid gap-3 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-muted">ICU plural</dt>
          <dd className="mt-1 font-medium">{t("items", { count: 12 })}</dd>
        </div>
        <div>
          <dt className="text-muted">Number</dt>
          <dd className="mt-1 font-medium">
            {t("credits", { amount: 2_880_000 })}
          </dd>
        </div>
        <div>
          <dt className="text-muted">Date</dt>
          <dd className="mt-1 font-medium">{format.dateTime(date, "short")}</dd>
        </div>
      </dl>
    </section>
  );
}

const meta = {
  title: "Foundation/Internationalization",
  component: InternationalizationDemo,
  parameters: { layout: "centered" },
} satisfies Meta<typeof InternationalizationDemo>;

export default meta;
type Story = StoryObj<typeof meta>;

export const ActiveLocale: Story = {};

export const SimplifiedChinese: Story = {
  globals: { locale: "zh-CN" },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("heading", { name: "多语言基础" }),
    ).toBeVisible();
  },
};

export const TraditionalChinese: Story = {
  globals: { locale: "zh-TW" },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("heading", { name: "多語言基礎" }),
    ).toBeVisible();
  },
};
