import type { formats } from "@/i18n/formats";
import type { AppLocale } from "@/i18n/config";
import type { AppMessages } from "@/i18n/messages";

declare module "next-intl" {
  interface AppConfig {
    Locale: AppLocale;
    Messages: AppMessages;
    Formats: typeof formats;
  }
}
