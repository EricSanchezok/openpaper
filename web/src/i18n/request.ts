import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { localeCookieName } from "@/i18n/config";
import { formats } from "@/i18n/formats";
import { resolveLocale } from "@/i18n/locale";
import { loadMessages } from "@/i18n/messages";

export default getRequestConfig(async () => {
  const [cookieStore, headerStore] = await Promise.all([cookies(), headers()]);
  const locale = resolveLocale({
    cookieLocale: cookieStore.get(localeCookieName)?.value,
    acceptLanguage: headerStore.get("accept-language"),
  });

  return {
    locale,
    messages: await loadMessages(locale),
    formats,
    timeZone: "UTC",
  };
});
