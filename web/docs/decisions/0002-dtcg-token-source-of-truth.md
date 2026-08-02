# ADR 0002: Keep design-token values in repository DTCG files

- Status: Accepted
- Date: 2026-08-02

## Context

Scholens needs multiple themes and Light/Dark appearances without visual drift
between Figma, application components, Tailwind utilities, and Storybook.
Allowing each surface to own color values would create several competing
sources of truth.

## Decision

After the initial Figma calibration, DTCG JSON under
`src/design-system/tokens/` is the numeric source of truth.

- Style Dictionary generates CSS variables and TypeScript metadata.
- Components consume semantic variables, never primitive palette values.
- Raw brand colors are not written inside components.
- Generated files are not edited by hand.
- Theme and Appearance remain independent dimensions.
- Figma continues to express visual intent and receives synchronized values
  through an explicit token update workflow.

## Consequences

Theme changes propagate predictably to the app and Storybook. Token updates
require generation and drift checks, but reviews can distinguish deliberate
design changes from accidental local styling.
