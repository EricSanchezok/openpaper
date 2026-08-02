# 0004 — Locale-neutral application internationalization

Status: Accepted
Date: 2026-08-02
Owners: Scholens web

## Context

The replacement frontend needs English, Simplified Chinese, and Traditional
Chinese before product routes are built. It needs Server Component support,
typed ICU messages, Storybook isolation, and a stable preference contract. The
authenticated workspace is not an indexable marketing site, so locale-prefixed
URLs would add routing and navigation state without a product benefit.

## Decision

Use `next-intl` with locale-neutral App Router URLs. Resolve account preference,
then the `scholens-locale` cookie, then `Accept-Language`, and finally English.
Load only the active request dictionary in the root provider. Keep UI locale
independent from Reader content translation. The repository message catalogs
and named formats are the runtime source of truth and are checked for parity.

Account preference remains an integration point: the future auth bootstrap may
seed the locale cookie from a profile locale, but the frontend will not invent
an unsupported profile-update endpoint.

## Alternatives considered

- Locale-prefixed routes: useful for localized public SEO pages, but unnecessary
  for the authenticated application and disruptive to stable resource URLs.
- A custom dictionary/context layer: avoids a dependency but duplicates ICU,
  Server Component, formatting, and type-safety behavior.
- Loading all dictionaries in every browser bundle: simple, but scales poorly
  and weakens the server-first boundary.

## Consequences

Every user-facing message must exist in all supported catalogs. Server
Components can translate without shipping extra locale data, while interactive
components inherit one client provider. Switching locale writes a cookie and
refreshes the current route. Public localized pages may later introduce route
segments through a superseding ADR.

## Validation

`pnpm i18n:check` enforces key and ICU argument parity. Unit tests cover locale
resolution, Storybook proves toolbar-driven dictionaries, and Playwright checks
cookie-to-root-provider integration.
