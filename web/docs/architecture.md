# Frontend Architecture

## Goals

- Keep the replacement `web/` independent from the legacy `client/`.
- Organize product code by user-facing capability, not by technical file type.
- Make ownership of server, URL, form, and local UI state explicit.
- Keep routes thin and shared primitives free of product vocabulary.
- Delay abstractions until a real use case exists.

## Dependency direction

Dependencies flow inward toward stable foundations:

```text
src/app
  -> src/features/*
      -> src/components/feedback
      -> src/components/ui
      -> src/design-system
      -> src/lib

src/components/feedback -> src/components/ui + src/design-system
src/components/ui       -> src/design-system + src/lib/utilities
src/design-system       -> framework packages only
src/lib                 -> framework/client libraries only
```

The reverse directions are forbidden. In particular:

- `components/ui` must not import features, API clients, Query hooks, or routes.
- `design-system` must not import components or product code.
- `lib` must not import features or product components.
- A feature must not reach into another feature's private files.
- Nothing under `web/` imports from `client/`.

If two features need the same product behavior, first decide whether it is a
true cross-product pattern. Promote only that narrow pattern to a shared
component; do not create an unowned `common/` or `shared/` dumping ground.

## Route boundary

`src/app` owns Next.js routing, layouts, metadata, error boundaries, and
provider composition. Route files may assemble a feature and pass route/search
parameters, but must not contain substantial request logic, domain transforms,
or large UI implementations.

Server Components are the default. Add `"use client"` only at the smallest
interactive boundary. Browser-only libraries, hooks, and providers must not
leak into a server module.

## Feature slices

Create a feature directory only when its first real route or reusable product
interaction is implemented. Do not add empty Authentication, Library, Project,
or Reader shells in advance.

Suggested shape, using Library only as an example:

```text
src/features/library/
├── api/          # query options, mutations, feature-facing API adapters
├── components/   # Library-specific product components
├── hooks/        # interaction orchestration, not generic utilities
├── schemas/      # form and URL schemas owned by the feature
├── lib/          # pure Library transforms
├── routes/       # optional route-level compositions when a page is large
└── index.ts      # intentionally small public API
```

Not every feature needs every folder. Start with the fewest files that express
the boundary. Private files are imported relatively inside the feature; code
outside the feature imports only its public `index.ts` API.

## State ownership

Choose the narrowest durable owner:

| State                                                  | Owner                                       |
| ------------------------------------------------------ | ------------------------------------------- |
| Backend resources, loading, caching, invalidation      | TanStack Query                              |
| Shareable filters, selection in a URL, active tab/page | Route/search params                         |
| Form values and validation                             | React Hook Form + Zod                       |
| Ephemeral interaction state                            | Local React state                           |
| Stable cross-tree UI preference, such as appearance    | A focused Context                           |
| Authentication/session truth                           | The auth integration and typed API contract |

Do not copy Query data into Context or a global store. Do not use Context as an
event bus. A new global state library requires evidence that URL, Query, forms,
local state, and a focused Context cannot model the requirement, plus an ADR.

## Data flow

The normal path is:

```text
public OpenAPI snapshot
  -> generated TypeScript paths
  -> shared typed transport
  -> feature query options/mutations
  -> route or feature component
  -> UI and feedback primitives
```

Components never call `fetch` directly. Feature code does not define duplicate
backend DTOs. Domain display models may exist when they deliberately transform
an API response for the UI.

## Naming and exports

- Files use kebab-case; React components and types use PascalCase.
- Hooks begin with `use`; Query key factories end with `Keys`.
- Avoid `utils.ts`, `helpers.ts`, and `common.ts`. Name files by responsibility.
- Barrel exports exist only at a stable public boundary. Avoid barrels inside a
  feature because they hide dependency cycles.
- One module should have one clear reason to change.

## Architecture changes

Refactors within these boundaries do not require a decision record. Introducing
a new state library, second primitive system, second icon set, cross-feature
event bus, UI package, registry, or different token authority does. Record the
decision before implementation using the template in `docs/decisions/`.
