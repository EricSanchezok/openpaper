# Authentication Foundation

This document is the implementation contract for Scholens authentication. It
defines the shared session runtime and the complete `/login` entry lifecycle.

## Scope

The foundation owns:

- session bootstrap, sign-in, sign-out, and cross-tab coordination;
- typed authentication errors and localized error mapping;
- reusable form schemas and accessible form controls;
- responsive authentication surfaces and deterministic mock scenarios.

It does not own OAuth, social login, referral codes, or post-login product
navigation beyond the validated `returnTo` handoff.

## Route and lifecycle contract

Authentication is a single responsive route. Do not add separate pages for
registration, recovery, verification, or reset:

```text
/login
/login?mode=register
/login?mode=forgot
/login?mode=verify&token=...
/login?mode=reset&token=...
```

The public `AuthenticationMode` values are `sign-in`, `register`, `forgot`,
`verify`, and `reset`. A missing or unknown mode renders sign-in. Mode links use
`buildAuthenticationHref()` so a validated internal `returnTo` is retained and
action tokens are removed when they no longer apply.

- Sign-in redirects with `router.replace(returnTo ?? "/")`.
- Register and forgot-password always render an ambiguous check-inbox result.
- Register stores only the pending email in `sessionStorage`; passwords and
  action tokens are never stored.
- Verify executes a present token once. A missing token renders an invalid-link
  result without a request.
- Reset validates and submits a present token, then replaces the URL with the
  token-free sign-in route. It never signs the user in automatically.
- An already authenticated visitor leaves ordinary auth modes immediately.
  Verify and reset action links are allowed to complete first.
- Session bootstrap uses a fixed-size skeleton. An unavailable session service
  leaves the form usable with an explicit retry notice.

## Responsive contract

Authentication uses one component tree, one form, and one API flow at every
width. Do not create mobile-only JSX or routes.

| Range   | Width         | Layout intent                                                |
| ------- | ------------- | ------------------------------------------------------------ |
| Mobile  | 320–639px     | Single column, 16px safe page padding, full-width submit     |
| Tablet  | 640–1023px    | Narrower maximum surface with increased outer breathing room |
| Desktop | 1024px and up | Centered surface with optional brand whitespace              |

Page structure may use viewport breakpoints. Reusable surfaces and form groups
prefer container queries so they remain portable. `AuthViewport` supplies
`100dvh`, safe-area padding, scroll behavior, and the minimum supported width.
The browser must be allowed to scroll when a virtual keyboard reduces the
visual viewport.

Required review widths are 320, 390, 768, and 1440 pixels. At 320px there must
be no horizontal page scroll. At 200% text zoom the form order, current field,
error, and submit action must remain usable.

## Session state machine

```text
bootstrapping
  ├─ refresh + /me succeed ─────────────> authenticated
  ├─ refresh cookie missing/expired ────> anonymous
  └─ network/service failure ───────────> unavailable

authenticated ── sign out ─────────────> anonymous
unavailable ──── retry bootstrap ──────> bootstrapping
```

`unavailable` is deliberately distinct from `anonymous`: connectivity failure
must never look like a logged-out account.

- Access tokens live only in module memory.
- Refresh tokens remain in HttpOnly cookies.
- Protected requests may refresh once and replay once after a 401.
- Authentication endpoints never trigger recursive refresh.
- Refresh is single-flight within one tab and locked across tabs. The fallback
  lease stored in `localStorage` contains only an opaque owner and expiry, never
  a token or actor.
- `BroadcastChannel` sends only `signed-in` and `signed-out` events. A receiving
  tab obtains its own access token through refresh.
- Signing out clears the access token, actor, and TanStack Query cache.
- `returnTo` accepts only an internal relative path.

## Error contract

The frontend maps stable error codes rather than backend prose:

- `auth_invalid_credentials`
- `auth_rate_limited`
- `auth_session_missing`
- `auth_session_expired`
- `auth_token_invalid_or_expired`
- `auth_verification_token_invalid`
- `auth_reset_token_invalid`
- `auth_service_unavailable`
- `validation_error`

Unknown failures use localized generic copy and retain the request/correlation
ID for support. Sign-in failures intentionally do not distinguish nonexistent,
inactive, locked, or wrong-password accounts. Registration, resend, and forgot
password flows must preserve ambiguous success responses.

`ApiError.retryAfterSeconds` is parsed from either form of `Retry-After`: delta
seconds or an HTTP date. Feature code displays localized retry guidance and
never parses backend English messages.

## Form contract

Schemas live in `src/features/authentication/schemas.ts`. Confirm-password
fields are validated locally and removed from the wire payload. Passwords use
the backend rule of at least 12 characters; the UI must not invent a strength
score or extra composition rules.

Use `Field` as the accessible composition boundary. `FieldControl` establishes
the control ID and connects the label, optional description, error message,
`aria-invalid`, and `aria-describedby`. `PasswordInput` owns only password
visibility; the caller provides localized accessible labels and autocomplete.

## Figma ↔ Code mapping

| Figma intent                     | Code owner                                      | Rule                                                     |
| -------------------------------- | ----------------------------------------------- | -------------------------------------------------------- |
| Authentication screen spacing    | `AuthViewport` plus route composition           | Recreate intent responsively, not layer coordinates      |
| Text field and validation states | `Field`, `Input`, `PasswordInput`               | Use shared focus, invalid, disabled, loading semantics   |
| Submit and secondary actions     | `Button`, `LinkButton`, `IconButton`            | Reuse variants; no page-local button implementation      |
| Form-level notice                | `Alert`                                         | Feature owns localized copy                              |
| Transient confirmation           | application `ToastProvider` and toast API       | Do not create page-local toast stacks                    |
| Light/Dark and spacing values    | semantic DTCG tokens                            | Repository token values are canonical                    |
| Desktop and Mobile key frames    | Storybook viewports and responsive route styles | One DOM/state machine; key frames are acceptance anchors |

## Mock scenarios

Storybook and tests use explicit MSW handlers for success, invalid credentials,
rate limiting, expired verification/reset tokens, missing/expired/reused
refresh, `/me`, slow responses, offline, and service unavailable. Unhandled
requests fail immediately. The Auth session harness covers all four session
states without a live backend.

The executable lifecycle catalogue is
`src/features/authentication/authentication-page.stories.tsx`. It is the first
place to review sign-in, invalid credentials, rate limiting, registration,
forgot password, verify, reset, mobile, and Simplified Chinese behavior.

Playwright route coverage lives in `tests/e2e/authentication.spec.ts`; it owns
URL normalization, missing-token behavior, safe `returnTo`, wire-payload and
browser-storage boundaries, 320px overflow, locale selection, and the route
axe scan.

## Change gate

Authentication changes must preserve the single route, single responsive DOM,
shared session provider, public transport, generated API types, and shared
schemas. Run unit, Storybook browser, Playwright, i18n, API, token, type, lint,
format, and production build gates before merging.
