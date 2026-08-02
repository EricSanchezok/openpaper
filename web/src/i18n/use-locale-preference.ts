"use client";

import { useRouter } from "next/navigation";
import { useLocale } from "next-intl";
import { useCallback, useTransition } from "react";

import {
  isAppLocale,
  localeCookieMaxAge,
  localeCookieName,
  localeDirection,
  type AppLocale,
} from "@/i18n/config";

function persistLocaleCookie(locale: AppLocale) {
  document.cookie = `${localeCookieName}=${locale}; path=/; max-age=${localeCookieMaxAge}; samesite=lax`;
}

export function useLocalePreference() {
  const locale = useLocale();
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  const setLocale = useCallback(
    (nextLocale: AppLocale) => {
      if (!isAppLocale(nextLocale) || nextLocale === locale) return;
      persistLocaleCookie(nextLocale);
      document.documentElement.lang = nextLocale;
      document.documentElement.dir = localeDirection(nextLocale);
      startTransition(() => router.refresh());
    },
    [locale, router],
  );

  return {
    locale: isAppLocale(locale) ? locale : "en",
    pending,
    setLocale,
  };
}
