# Architecture Decision Records

Use a short ADR when deliberately changing a foundational rule: adding a global
state library, another primitive or icon system, a shared UI package, a private
registry, a cross-feature event mechanism, a new token authority, or a different
API transport.

Name records `NNNN-short-decision-name.md`. Once accepted, do not rewrite the
history; add a later ADR that supersedes it.

## Accepted decisions

- [ADR 0001: Independent web application](./0001-independent-web-application.md)
- [ADR 0002: DTCG token source of truth](./0002-dtcg-token-source-of-truth.md)
- [ADR 0003: Generated public API contract](./0003-generated-public-api-contract.md)
- [ADR 0004: Locale-neutral application internationalization](./0004-locale-neutral-next-intl.md)
- [ADR 0005: Memory-token authentication session](./0005-memory-token-auth-session.md)
- [ADR 0006: Fixed local-development port block](./0006-local-development-port-contract.md)
- [ADR 0007: Generated design-system contract](./0007-generated-design-system-contract.md)

## Template

```markdown
# NNNN — Decision title

Status: Proposed | Accepted | Superseded
Date: YYYY-MM-DD
Owners: names or team

## Context

What concrete problem and constraints require a decision?

## Decision

What will we do? State boundaries and non-goals.

## Alternatives considered

What credible alternatives were rejected and why?

## Consequences

What becomes easier, harder, or newly required?

## Validation

How will we know the decision works, and when should it be revisited?
```
