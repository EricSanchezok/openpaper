# Scholens agent development guide

This file is the mandatory entry point for agents modifying this repository.
It defines navigation and guardrails; detailed rules stay in their canonical
documents so they do not drift across multiple copies.

## Read before changing code

Always read the documents relevant to the task before editing:

| Area                                            | Required reading                                                                           |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Product behavior or terminology                 | [`PRODUCT.md`](./PRODUCT.md)                                                               |
| Local services, ports, environment, or commands | [`DEVELOPMENT.md`](./DEVELOPMENT.md)                                                       |
| Replacement frontend (`web/`)                   | [`web/docs/README.md`](./web/docs/README.md) and its task-specific guide                   |
| Backend API or domain behavior                  | [`server/README.md`](./server/README.md)                                                   |
| Background processing                           | [`jobs/README.md`](./jobs/README.md)                                                       |
| Data or service ownership                       | [`docs/architecture/data-ownership.md`](./docs/architecture/data-ownership.md)             |
| Current backend capabilities                    | [`docs/architecture/backend-capabilities.md`](./docs/architecture/backend-capabilities.md) |
| Production deployment                           | [`deploy/production/README.md`](./deploy/production/README.md)                             |

For new `web/` product work, also complete
[`web/docs/new-feature-checklist.md`](./web/docs/new-feature-checklist.md).

## Repository boundaries

- `web/` is the replacement frontend and the canonical target for new product
  development.
- `client/` is the legacy comparison frontend. Do not import from it, share
  runtime code with it, or add new product features to it unless the user
  explicitly requests legacy maintenance.
- `server/` owns the FastAPI application and synchronous product APIs.
- `jobs/` owns asynchronous workers and their job-facing API.
- Product code must respect the schema and service ownership documented in
  `docs/architecture/data-ownership.md`.
- Do not create compatibility layers between the old and new frontends. Evolve
  the public API contract deliberately instead.

## Replacement frontend rules

The canonical rules live in [`web/docs`](./web/docs/README.md). In particular:

- routes compose features; they do not contain large business implementations;
- product code is organized as vertical feature slices when implementation
  actually begins;
- generic controls belong in `components/ui`, shared asynchronous patterns in
  `components/feedback`, and product components inside their feature;
- components use semantic design tokens and the Iconoir wrapper—no raw brand
  colors or second icon system;
- server state uses TanStack Query, shareable navigation state uses the URL,
  forms use React Hook Form and Zod, and local interaction state stays local;
- backend wire types are generated from the committed public OpenAPI snapshot;
  do not handwrite duplicate DTOs;
- every reusable component needs isolated Storybook coverage, interaction
  states, keyboard behavior, narrow-content coverage, and Light/Dark review.
- interface copy follows `web/docs/internationalization.md`; UI locale and
  Reader content translation are separate product concepts.

Do not mechanically recreate Figma layers or absolute coordinates. Figma owns
layout intent, visual hierarchy, interaction states, and acceptance; code owns
responsive behavior, accessibility, runtime contracts, and component APIs.

## Generated artifacts

Do not edit generated files directly. Change their source and regenerate them.

- Design tokens: edit `web/src/design-system/tokens/`, then run
  `pnpm tokens:build` from `web/`.
- Frontend API types: update the FastAPI contract and public snapshot, then run
  `pnpm api:generate` from `web/`.
- Commit source and generated outputs together.

## Verification

Run checks proportional to the change. The full replacement-frontend gate is:

```bash
cd web
pnpm tokens:check
pnpm api:check
pnpm i18n:check
pnpm lint
pnpm format:check
pnpm typecheck
pnpm test
pnpm test:storybook
pnpm build-storybook
pnpm build
pnpm test:e2e
```

Use the targeted backend tests and Ruff checks described in `server/README.md`
when backend files change. A generated or documentation-only change may use a
smaller relevant subset, but the final handoff must state exactly what ran.

## Change hygiene

- Preserve unrelated user or agent changes in a dirty worktree.
- Never combine unrelated work in one commit.
- For multi-step implementation, create a verified commit at each coherent
  recovery point when commits are within the requested workflow.
- Before staging, inspect the exact changed files; do not stage another agent's
  work merely because it is present.
- Architecture changes require an ADR under `web/docs/decisions/` or the
  appropriate service-level architecture documentation.
- Documentation must change in the same commit as the behavior that invalidates
  it.
- Keep upstream copyright, license, provenance, migration, and evaluation
  references unless their removal has been explicitly validated.
