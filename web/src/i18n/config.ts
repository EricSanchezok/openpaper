export const locales = ["en", "zh-CN"] as const;

export type AppLocale = (typeof locales)[number];

export const defaultLocale: AppLocale = "en";
export const localeCookieName = "scholens-locale";
export const localeCookieMaxAge = 60 * 60 * 24 * 365;

export function isAppLocale(value: unknown): value is AppLocale {
  return typeof value === "string" && locales.includes(value as AppLocale);
}

const localeDirections: Record<AppLocale, "ltr" | "rtl"> = {
  en: "ltr",
  "zh-CN": "ltr",
};

export function localeDirection(locale: AppLocale): "ltr" | "rtl" {
  return localeDirections[locale];
}
