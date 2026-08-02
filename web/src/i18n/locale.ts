import { defaultLocale, isAppLocale, type AppLocale } from "@/i18n/config";

function localeCandidates(value: string): string[] {
  return value.trim().replaceAll("_", "-").split("-").filter(Boolean);
}

export function normalizeLocale(value: unknown): AppLocale | undefined {
  if (typeof value !== "string" || value.trim() === "") return undefined;

  const normalized = value.trim().replaceAll("_", "-");
  if (isAppLocale(normalized)) return normalized;

  const [language, regionOrScript] = localeCandidates(normalized).map((part) =>
    part.toLowerCase(),
  );

  if (language === "en") return "en";
  if (language !== "zh") return undefined;

  if (["hant", "tw", "hk", "mo"].includes(regionOrScript ?? "")) {
    return "zh-TW";
  }

  return "zh-CN";
}

export function localeFromAcceptLanguage(
  acceptLanguage: string | null | undefined,
): AppLocale | undefined {
  if (!acceptLanguage) return undefined;

  return acceptLanguage
    .split(",")
    .map((entry, index) => {
      const [tag = "", ...parameters] = entry.trim().split(";");
      const qualityParameter = parameters.find((parameter) =>
        parameter.trim().startsWith("q="),
      );
      const quality = qualityParameter
        ? Number(qualityParameter.trim().slice(2))
        : 1;
      return {
        index,
        locale: normalizeLocale(tag),
        quality: Number.isFinite(quality) ? quality : 0,
      };
    })
    .filter(
      (
        candidate,
      ): candidate is {
        index: number;
        locale: AppLocale;
        quality: number;
      } => Boolean(candidate.locale) && candidate.quality > 0,
    )
    .sort(
      (left, right) => right.quality - left.quality || left.index - right.index,
    )[0]?.locale;
}

export function resolveLocale({
  accountLocale,
  cookieLocale,
  acceptLanguage,
}: {
  accountLocale?: string | null;
  cookieLocale?: string | null;
  acceptLanguage?: string | null;
}): AppLocale {
  return (
    normalizeLocale(accountLocale) ??
    normalizeLocale(cookieLocale) ??
    localeFromAcceptLanguage(acceptLanguage) ??
    defaultLocale
  );
}
