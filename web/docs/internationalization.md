# Internationalization

Scholens supports `en`, `zh-CN`, and `zh-TW` through `next-intl`. Interface
locale is application chrome and product copy; it is not the Reader's paper
translation language. Keep those settings, persistence rules, and backend
contracts separate.

## Routing and resolution

Authenticated application URLs stay locale-neutral. Do not add `/en`,
`/zh-CN`, or `/zh-TW` route segments unless the product later needs localized
public, indexable pages and records a superseding ADR.

The effective interface locale is resolved in this order:

1. Account locale supplied by the future authenticated profile bootstrap.
2. The `scholens-locale` cookie.
3. The browser `Accept-Language` header.
4. English.

The current public profile update contract does not accept locale. Until the
auth integration owns account-locale persistence, `useLocalePreference` writes
the cookie and refreshes Server Components. Do not invent a second preference
store.

## Files and responsibilities

```text
src/i18n/
├── config.ts                 # supported locales and cookie contract
├── formats.ts                # named date and number formats
├── locale.ts                 # normalization and deterministic resolution
├── request.ts                # per-request server locale and dictionary
├── messages.ts               # active-dictionary loader
├── messages/{locale}.json    # ICU message catalogs
└── use-locale-preference.ts  # smallest client-side preference boundary
```

The root layout loads only the active dictionary and gives it to
`NextIntlClientProvider`. Server Components are the default consumers. Use
`useTranslations` only inside an existing Client Component boundary; do not
move a component client-side solely to translate static copy.

## Message rules

- User-visible product copy must use a stable namespaced message key.
- Keep keys semantic (`Library.empty.title`), not copies of English text.
- Reuse `Common` only for genuinely identical actions or nouns. Feature copy
  stays in the feature namespace.
- Use ICU arguments for values, plurals, and selection. Do not concatenate
  translated fragments.
- Use named formats from `formats.ts` for dates and numbers. Do not rely on a
  developer machine's locale or time zone.
- Backend error codes map to frontend message keys. Never render raw backend
  exception text to users.
- Primitive components accept accessible labels and content from callers;
  product components perform the translation.

`global-error.tsx` intentionally uses a minimal English emergency message. It
replaces the root layout and must still render when locale initialization is
the failure. All normal route and component errors use the active dictionary.

## Adding or changing copy

1. Add the same namespaced key to `en.json`, `zh-CN.json`, and `zh-TW.json`.
2. Preserve the same ICU argument names in every locale.
3. Run `pnpm i18n:check`; missing, extra, or incompatible messages fail.
4. Review the component in Storybook using all three Locale toolbar values,
   long content, and the Narrow panel viewport.
5. Add an interaction or route test when locale changes behavior beyond text.

To add a locale, update `config.ts`, add its catalog and loader, include it in
the Storybook provider and toolbar, then extend locale resolution tests. Adding
a locale is incomplete until message parity, typography, layout, keyboard, and
accessibility checks pass.

## Storybook and tests

The Storybook Locale toolbar selects a real `NextIntlClientProvider` dictionary;
it does not merely change the HTML language attribute. Stories should normally
inherit this provider instead of defining their own.

Use unit tests for locale resolution, Storybook for translated component and
layout states, and Playwright for request/cookie/provider integration. Keep
tests deterministic with the committed dictionaries and UTC unless a feature
explicitly tests another time zone.
