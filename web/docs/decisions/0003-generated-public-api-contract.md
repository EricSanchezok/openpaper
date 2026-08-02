# ADR 0003: Generate frontend API types from a public OpenAPI snapshot

- Status: Accepted
- Date: 2026-08-02

## Context

The backend will continue evolving during the frontend rewrite. Handwritten
frontend DTOs would silently diverge, while generating types from a running
backend would make builds non-deterministic.

## Decision

Treat `server/openapi/public-v1.json` as the committed public API snapshot.

- The snapshot is generated deterministically from `FastAPI app.openapi()` and
  filtered to public `/api/v1` routes.
- `openapi-typescript` generates frontend schema types from the local snapshot.
- `openapi-fetch` provides the typed transport boundary.
- Snapshot and generated type drift are checked in CI.
- Feature code owns query keys and domain-facing adapters; it does not handwrite
  backend wire types.
- The frontend build never requires a running backend.

## Consequences

Backend contract changes become visible code-review events. Regeneration adds a
small workflow step, but it prevents accidental schema drift and keeps local and
CI builds reproducible.
