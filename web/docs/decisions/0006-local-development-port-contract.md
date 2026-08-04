# 0006 — Reserve a fixed local-development port block

Status: Accepted
Date: 2026-08-04
Owners: Scholens maintainers
Supersedes: the port allocation in ADR 0001

## Context

Scholens is developed alongside Account Center, Scholight, and Synergy. Reusing
common framework defaults such as `3000` made it easy to connect a browser,
callback, or test to the wrong product. Automatic port fallback made the failure
harder to notice and invalidated CORS, cookie, and callback assumptions.

## Decision

Reserve the `7300-7399` host-port block for Scholens local development. The
canonical allocations are maintained in the root `DEVELOPMENT.md` and enforced
by executable start commands:

- replacement Web `7300`;
- Server API `7301`;
- Jobs API `7302`;
- legacy comparison client `7303`;
- Storybook `7306`;
- Flower `7307`.

Local application processes bind to `127.0.0.1`, use exact ports, and fail when
their port is occupied. Daily startup commands must not auto-increment ports,
install dependencies, or apply migrations. Shared infrastructure keeps its
separate allocations documented in `DEVELOPMENT.md`.

## Alternatives considered

- **Keep framework defaults.** Rejected because several products need the same
  defaults and accidental cross-product connections are difficult to diagnose.
- **Allow automatic fallback.** Rejected because the displayed port no longer
  matches configured callbacks, CORS origins, service URLs, or browser tests.
- **Choose ports ad hoc per developer.** Rejected because it prevents committed,
  deterministic local contracts.

## Consequences

Developers can run the Sanchez Cloud products concurrently and identify a
service from its port. A conflict now stops startup and must be resolved
explicitly. Changes to an allocation require coordinated updates to environment
catalogs, executable commands, tests, documentation, and this decision record.

## Validation

- Package and Python entrypoints bind to the documented loopback ports.
- Server tests retain the local database endpoint guard.
- Documentation and architecture checks run in CI.
- Opening `127.0.0.1:7300` and `127.0.0.1:7301/docs` reaches Web and Server
  respectively when the default profile is running.
