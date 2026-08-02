# Scholens Web Foundation

`web/` is the independent replacement frontend foundation. It does not import
from the legacy `client/` and intentionally contains no Scholens product routes
yet.

## Local commands

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm dev                 # http://localhost:3000
pnpm storybook           # http://localhost:6006, no API required
pnpm test
pnpm test:storybook
pnpm test:e2e
```

The legacy comparison client remains available at `http://localhost:3001`.

## Boundaries

- `src/components/ui`: request-free primitives without product vocabulary.
- `src/components/feedback`: reusable async and empty-state patterns.
- `src/design-system`: DTCG sources, generated tokens, themes, and Iconoir wrapper.
- `src/lib/api`: generated OpenAPI types, transport, and normalized errors.
- `src/lib/query`: Query Client conventions.
- `src/app`: routes and provider composition only.

Run `pnpm tokens:build` after editing DTCG sources and `pnpm api:generate`
after the committed public OpenAPI snapshot changes. Generated files are
committed and checked for drift in CI.

## Engineering handbook

The rules for extending this foundation live in [`docs/`](./docs/README.md).
Read the relevant guide before adding a feature, component, token, API call, or
test:

- [`architecture.md`](./docs/architecture.md): dependency direction, feature
  slices, state ownership, and route boundaries.
- [`component-development.md`](./docs/component-development.md): component
  classification, API design, external component intake, and Storybook rules.
- [`design-tokens.md`](./docs/design-tokens.md): Figma/DTCG workflow, semantic
  styling, themes, and generated artifacts.
- [`api-development.md`](./docs/api-development.md): public OpenAPI snapshots,
  typed transport, query conventions, and coordinated schema changes.
- [`testing.md`](./docs/testing.md): unit, Storybook browser, MSW, accessibility,
  and Playwright responsibilities.
- [`new-feature-checklist.md`](./docs/new-feature-checklist.md): the required
  checklist for every new vertical slice.

Architecture exceptions require a short decision record in
[`docs/decisions/`](./docs/decisions/README.md); they must not be hidden inside a
feature implementation.
