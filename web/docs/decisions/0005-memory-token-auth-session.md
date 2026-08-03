# 0005 — Memory-token authentication session

Status: Accepted
Date: 2026-08-02
Owners: Scholens web

## Context

The replacement frontend needs session bootstrap, typed authenticated requests,
refresh-token rotation, multi-tab behavior, and a distinct unavailable state
before authentication pages are implemented. Persisting bearer tokens in web
storage would expand the impact of script injection, while independent refresh
attempts can race across requests and tabs.

## Decision

Access tokens exist only in module memory. The refresh token remains in the
server-managed HttpOnly cookie. One focused `AuthProvider` owns the actor and
four-state session status. Protected requests attach the memory token, refresh
once on 401, and replay once; authentication endpoints never recurse.

Refresh calls are single-flight within a tab and use the browser Locks API,
with an opaque expiring local-storage lease as fallback, across tabs. The lease
never contains credentials. `BroadcastChannel` synchronizes only signed-in and
signed-out events; receiving tabs refresh independently and tokens are never
broadcast.

## Alternatives considered

- Persisting the access token in local or session storage was rejected because
  it makes bearer credentials durable and directly readable by injected code.
- Sharing the access token over `BroadcastChannel` was rejected because it
  distributes credentials beyond the tab that obtained them.
- Treating every bootstrap failure as anonymous was rejected because service
  outages would incorrectly present sign-in UI and lose the user's context.
- Adding a general global state library was rejected because a focused Context
  and TanStack Query cache have clear, separate ownership.

## Consequences

Reloading a tab always performs a refresh before `/me`. Multi-tab sign-in may
briefly show bootstrapping while the receiving tab obtains its own token. The
session layer must retain tests for single-flight, one replay, no recursion,
cross-tab events, and unavailable behavior.

## Validation

Unit tests verify memory-only storage, concurrent refresh coalescing, one-time
replay, authentication endpoint exclusion, safe `returnTo`, and token-free
cross-tab events. Storybook exercises authenticated, anonymous, unavailable,
and bootstrapping states without a backend.
