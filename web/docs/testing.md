# Testing Strategy

## Test by responsibility

| Layer                                      | Tool                            | Purpose                                                                 |
| ------------------------------------------ | ------------------------------- | ----------------------------------------------------------------------- |
| Pure utilities and focused component logic | Vitest + Testing Library        | Fast deterministic behavior                                             |
| Component states and interactions          | Storybook + Vitest Browser Mode | Real Chromium, props, themes, keyboard, axe                             |
| Network-driven component behavior          | Storybook + MSW                 | Success, slow, empty, errors, offline, 401                              |
| Route/application contract                 | Playwright                      | Provider integration, navigation, critical flows, browser accessibility |
| Backend schema boundary                    | Pytest                          | Public OpenAPI snapshot and server configuration                        |

Prefer the lowest layer that catches the regression. Do not duplicate every
component assertion in Playwright.

## Required commands

```bash
pnpm tokens:check
pnpm api:check
pnpm lint
pnpm format:check
pnpm typecheck
pnpm test
pnpm test:storybook
pnpm build-storybook
pnpm build
pnpm test:e2e
```

CI runs these in Node.js 22 with a frozen pnpm lockfile.

## Storybook coverage

Use global toolbar controls instead of duplicating entire story files:

- Theme: Default, later additional independent themes.
- Appearance: Light and Dark.
- Locale: English, Simplified Chinese, Traditional Chinese.
- Viewport: Desktop, Narrow panel, Mobile.
- Network: Instant, Slow, Offline.
- Data: Populated, Empty, Error.

Each interactive component or product pattern covers relevant states, long
content, narrow width, keyboard interaction, and accessibility. `play`
functions assert outcomes rather than waiting arbitrary durations.

## MSW rules

- Stories and component tests never call a live API.
- Handlers model the public contract and return deterministic fixtures.
- Keep generic transport scenarios in `.storybook/msw` and feature-specific
  domain handlers beside the feature.
- Cover success, delay, empty, business error, server error, offline, and 401
  where the UI reacts differently.
- An unhandled request is a test design smell; explicitly add or intentionally
  document it rather than relying on a developer backend.

## Accessibility

Automated axe checks are a gate, not a complete audit. Also verify:

- Logical Tab and Shift+Tab order.
- Visible focus and Escape behavior.
- Dialog focus trapping and return focus.
- Accessible names for icon-only controls.
- Labels, descriptions, errors, and `aria-invalid` for forms.
- Status announcements for asynchronous changes when needed.
- Text zoom, narrow containers, long translations, and reduced motion.
- Contrast in both appearances.

Serious and critical axe violations fail Storybook tests. Critical product
flows receive a Playwright keyboard pass before release.

## Playwright scope

Use Playwright for a small set of high-value browser journeys, not exhaustive
component permutations. Tests should use stable roles and accessible names,
avoid implementation selectors, and create their own state. Network responses
must be deterministic unless a test is explicitly marked as an integration
test with the backend.

## Flake policy

- Never fix a race by adding an unconditional sleep.
- Wait for user-visible state or a specific network event.
- A flaky test is quarantined only with an owner and removal issue; it is not
  silently skipped.
- Browser console errors, unhandled requests, and React warnings are treated as
  defects.
