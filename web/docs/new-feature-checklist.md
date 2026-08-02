# New Feature Checklist

Use this checklist for every new route or substantial product capability.

## Before implementation

- [ ] Define the user outcome, entry point, exit point, and permissions.
- [ ] Identify canonical Figma frames and all relevant intermediate states.
- [ ] List populated, loading, slow, empty, partial, error, offline, retrying,
      unauthorized, and quota-limited behavior.
- [ ] Confirm the public OpenAPI contract exists; do not infer DTOs from old
      `client/` code.
- [ ] Decide which state belongs to the URL, TanStack Query, a form, local state,
      or an existing focused Context.
- [ ] Search existing UI, feedback, and product components before creating one.
- [ ] Identify user-visible copy, named formats, and every locale-sensitive
      behavior; keep Reader translation separate from interface locale.

## Structure

- [ ] Create `src/features/<feature>` only when real implementation begins.
- [ ] Keep the route thin and the feature public API small.
- [ ] Keep feature-private imports private; avoid cross-feature deep imports.
- [ ] Do not introduce `common`, `shared`, `misc`, or generic `utils` dumping
      grounds.
- [ ] Do not import from legacy `client/`.

## UI and behavior

- [ ] Use semantic tokens and the Scholens Iconoir wrapper.
- [ ] Reuse Radix/UI primitives without copying their behavior into product code.
- [ ] Cover keyboard, focus-visible, disabled, loading, validation, destructive,
      long-content, and narrow states as applicable.
- [ ] Use Async Feedback presentation appropriate to the surface; domain copy
      remains feature-owned.
- [ ] Verify Light and Dark. Do not patch appearance with call-site raw colors.
- [ ] Add namespaced messages for English and Simplified Chinese; verify long
      translations and do not concatenate fragments.

## Data

- [ ] Use generated OpenAPI types and the shared API transport.
- [ ] Define stable hierarchical Query keys.
- [ ] Pass abort signals and invalidate the narrowest affected cache keys.
- [ ] Standardize known errors and expose a request ID for unknown failures.
- [ ] Update OpenAPI snapshot/types, handlers, fixtures, and feature code together.

## Verification

- [ ] Add deterministic Default and state stories.
- [ ] Add interaction tests for real behavior, not only rendering.
- [ ] Add MSW success/slow/empty/error/offline/401 scenarios where relevant.
- [ ] Run Storybook axe checks and perform a keyboard pass.
- [ ] Add Playwright coverage only for route integration or a critical journey.
- [ ] Run the complete CI command set from `docs/testing.md`.
- [ ] Update the handbook or add an ADR if the implementation changes an
      architectural rule.

## Review questions

1. Can this feature be deleted without editing unrelated features?
2. Is each piece of state owned exactly once?
3. Does the UI work without a live backend in Storybook?
4. Would a backend schema change fail generation/type checks rather than drift
   silently?
5. Is a new abstraction solving an observed repeated behavior rather than a
   hypothetical future one?
