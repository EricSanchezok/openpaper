# ADR 0001: Build the replacement frontend as an independent application

- Status: Accepted
- Date: 2026-08-02
- Superseded in part: the development-port allocation in this record is replaced
  by [ADR 0006](./0006-local-development-port-contract.md).

## Context

The legacy `client/` reflects an older product model and backend contract. Sharing
components or business code with it would make the replacement inherit those
constraints and obscure when migration is actually complete.

## Decision

Build the replacement frontend entirely under the root `web/` directory.

- `web/` must not import from `client/`.
- The applications use separate package managers, build pipelines, and CI jobs.
- During migration, `web/` runs on port 3000 and `client/` runs on port 3001.
- Backend compatibility is expressed through the public API contract, not a
  frontend compatibility layer.
- Product functionality is rebuilt as vertical feature slices when its backend
  contract and interaction design are ready.

## Consequences

The two frontends can be compared safely and retired independently. Some UI may
be reimplemented instead of reused, but the new architecture stays legible and
does not accumulate temporary cross-application dependencies.
