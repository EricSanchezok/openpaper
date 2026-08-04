# ADR 0007: Generate and verify the design-system adapter

- Status: Accepted
- Date: 2026-08-04

## Context

The repository already used DTCG sources for color and dimensions, but the
Tailwind semantic aliases were maintained manually in global CSS. Repeated
compact font sizes and shadow recipes also appeared at component call sites.
The existing architecture check rejected raw colors, but it could not prove
Light/Dark semantic parity, adapter resolution, or Storybook's global review
axes. These gaps could produce silent drift as pages and themes multiply.

## Decision

- DTCG remains the numeric authority for primitives, theme palettes, semantic
  colors, dimensions, typography, and elevation effects.
- `src/design-system/adapters/tailwind.json` names the public Tailwind utility
  aliases. The token build appends the adapter to generated foundation CSS;
  global CSS does not define aliases manually.
- `pnpm design:check` validates Light/Dark token parity and direct resolution,
  adapter targets and self-reference, forbidden styling shortcuts, implemented
  feature stories, and Storybook's global review controls.
- Components consume named typography and elevation utilities instead of
  repeated arbitrary recipes.

## Alternatives considered

- Keep manual aliases and rely on review. This permits silent self-reference
  and missing aliases.
- Make Figma the numeric runtime authority. This adds plan/API dependency and
  does not remove the need for committed, reviewable build inputs.
- Add a CSS-in-JS theme runtime. This duplicates the existing token graph and
  creates a second styling system.

## Consequences

Token and adapter changes require regeneration, and new semantic roles must be
added deliberately. In return, Light/Dark parity, shared effects, and the
framework adapter are reviewable and machine checked. Figma remains the visual
acceptance source without becoming a build-time runtime dependency.

## Validation

`pnpm tokens:check` proves generated artifacts match sources.
`pnpm design:check` proves the graph and styling guardrails. Storybook browser
tests and production builds prove the generated utilities are consumable.
