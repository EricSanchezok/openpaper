import { describe, expect, it } from "vitest";

import {
  localeFromAcceptLanguage,
  normalizeLocale,
  resolveLocale,
} from "@/i18n/locale";

describe("locale resolution", () => {
  it.each([
    ["en-US", "en"],
    ["zh", "zh-CN"],
    ["zh-Hans", "zh-CN"],
    ["zh-Hant", "zh-CN"],
    ["zh_HK", "zh-CN"],
  ])("normalizes %s to %s", (input, expected) => {
    expect(normalizeLocale(input)).toBe(expected);
  });

  it("honors Accept-Language quality and stable source order", () => {
    expect(localeFromAcceptLanguage("zh-TW;q=0.8, en-US;q=0.9")).toBe("en");
    expect(localeFromAcceptLanguage("fr, zh-CN;q=0.7")).toBe("zh-CN");
  });

  it("resolves account, cookie, header, then default in that order", () => {
    expect(
      resolveLocale({
        accountLocale: "zh-TW",
        cookieLocale: "en",
        acceptLanguage: "en-US",
      }),
    ).toBe("zh-CN");
    expect(
      resolveLocale({ cookieLocale: "zh-CN", acceptLanguage: "en-US" }),
    ).toBe("zh-CN");
    expect(resolveLocale({ acceptLanguage: "de-DE" })).toBe("en");
  });
});
