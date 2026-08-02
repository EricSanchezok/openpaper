import type { AbstractIntlMessages } from "next-intl";

import type { AppLocale } from "@/i18n/config";
import englishMessages from "@/i18n/messages/en.json";

export type AppMessages = typeof englishMessages;

const messageLoaders = {
  en: () => import("@/i18n/messages/en.json").then((module) => module.default),
  "zh-CN": () =>
    import("@/i18n/messages/zh-CN.json").then((module) => module.default),
} satisfies Record<AppLocale, () => Promise<AbstractIntlMessages>>;

export async function loadMessages(locale: AppLocale) {
  return messageLoaders[locale]();
}
