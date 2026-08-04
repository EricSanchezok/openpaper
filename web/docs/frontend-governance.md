# Frontend Change Governance

This guide is the lifecycle contract for adding, changing, and deleting Web
surfaces. It keeps Figma, Storybook, tokens, components, product features, and
runtime behavior aligned without turning any one of them into a duplicate of
the others.

## Decide the owning layer first

Before editing, describe the user-visible problem and choose the narrowest
layer that owns it:

| Change                                          | Owner                                    | Evidence                                       |
| ----------------------------------------------- | ---------------------------------------- | ---------------------------------------------- |
| One composition's spacing or responsive layout  | Feature component                        | Canonical Figma frame + feature story          |
| Repeated control behavior or state              | `components/ui` or `components/feedback` | Primitive stories + consumers                  |
| Product behavior shared by real features        | Narrow shared product pattern            | Two concrete consumers + ADR when foundational |
| Color, type, radius, spacing, or elevation role | DTCG token graph                         | Light/Dark token output + foundation stories   |
| Server resource or mutation                     | Feature API layer + generated contract   | OpenAPI snapshot, MSW, Query tests             |
| Shareable navigation state                      | URL                                      | Route/Playwright evidence                      |

Do not fix a local symptom at a broader layer. Conversely, do not copy a
shared state into several call sites because changing the correct shared layer
feels more expensive.

## Source responsibilities

| Source                          | Owns                                                               | Does not own                                                           |
| ------------------------------- | ------------------------------------------------------------------ | ---------------------------------------------------------------------- |
| Product principles              | Durable user experience and terminology                            | CSS, component APIs, frame geometry                                    |
| Figma                           | Layout intent, hierarchy, interaction inventory, visual acceptance | Runtime contracts, responsive algorithms, accessibility implementation |
| DTCG sources in this repository | Numeric token values and semantic roles                            | Page-specific composition                                              |
| Storybook                       | Executable component and feature states                            | Backend integration or product requirements                            |
| Application code                | Responsive behavior, semantics, state ownership, API integration   | Independent visual language                                            |
| Playwright and backend tests    | Critical integrated behavior                                       | Exhaustive visual permutations                                         |

When sources disagree, use the priority documented in this handbook's index,
then resolve the disagreement explicitly. Never silently tune both sides until
they merely look close.

## Adding a page or module

1. Record the user outcome, route, permissions, canonical Figma page and
   node-specific frame links, plus every meaningful state.
2. Audit existing Storybook patterns and product components before proposing a
   new primitive. Similar pixels are not sufficient evidence of shared
   semantics.
3. Define state ownership and the public API contract. Create only the feature
   folders needed by the first real vertical slice.
4. Implement the smallest complete slice: route composition, real data path,
   deterministic stories, localized copy, responsive behavior, and critical
   interaction test.
5. Maintain a short acceptance table in the feature guide mapping Figma states
   to Storybook story IDs and runtime tests. A missing implementation state is
   visible debt, not an implicit TODO.
6. Run the complete gate before declaring the page ready for visual acceptance.

## Adding or changing a component

1. Search `components/ui`, `components/feedback`, feature components, and
   Storybook by behavior and accessible role.
2. Classify the component before writing it. Product vocabulary keeps it in the
   feature until reuse is proven.
3. Model finite states through semantic props and CVA. A caller may position a
   component but may not redefine its colors, focus, disabled, loading, or
   validation language.
4. Add or update stories for Default, variants, interaction states, long copy,
   narrow width, and both appearances as applicable. Use `play` functions for
   behavior and MSW for network states.
5. If a shared component changes, inspect every consumer. If only one consumer
   should change, add a meaningful variant or keep the change feature-owned;
   do not add a one-off color class.

## Adding or changing color, type, spacing, or elevation

1. Name the need as a role, such as `action.disabled-bg` or
   `elevation.overlay`, rather than as a color or coordinate.
2. Decide whether the role is primitive, theme palette, semantic appearance,
   composite effect, or Tailwind adapter. Reuse an existing role when its
   meaning matches.
3. Update DTCG sources. Light and Dark must expose the same semantic paths and
   types. Composite effects reference semantic color roles.
4. Add a Tailwind alias only in
   `src/design-system/adapters/tailwind.json`; the adapter CSS is generated.
5. Run `pnpm tokens:build`, `pnpm tokens:check`, and `pnpm design:check`, then
   review representative Storybook states in Light and Dark.
6. Sync the agreed role and values to Figma Theme Lab/Variables. Do not repair a
   token mismatch by changing individual frames or component call sites.

Raw colors, primitive palette references, `dark:` appearance patches,
`!important`, repeated 11/13px literals, and manual Tailwind theme aliases are
blocked by `design:check`.

## Modifying an existing page

Start from a concrete before/after acceptance statement. Determine whether the
problem belongs to the composition, a shared component, or a token. Update the
canonical Figma frame when visual intent changes, the Storybook state when
runtime presentation changes, and both when the contract changes. Preserve
responsive and accessibility behavior even when Figma shows only a desktop
frame.

Do not use a global token to fix one page, add a shared variant for a one-off
layout, or duplicate a shared component just to avoid reviewing its consumers.

## Deleting a page, module, component, or token

Deletion is a first-class change:

1. Search routes, feature exports, consumers, Query keys, messages, generated
   API usage, stories, fixtures, tests, docs, and Figma acceptance mappings.
2. Remove the entry point and its owned code in the same change. Do not leave a
   compatibility wrapper unless an active external consumer is documented.
3. Remove a shared component or token only after repository search proves zero
   consumers. Remove generated output through its source and regenerate.
4. Archive or label superseded Figma frames so design history remains
   discoverable; remove them from the active acceptance set.
5. Delete obsolete stories and tests, but retain or move coverage for behavior
   that still exists elsewhere.
6. Run architecture, design, i18n, docs, type, test, and build checks to catch
   dangling ownership.

## Figma and Storybook collaboration

Figma is the design-state inventory; Storybook is the executable-state
inventory. A feature handoff contains:

- a canonical Figma page and node-specific links, with obsolete alternatives
  moved to Archive;
- named states and annotations for behavior that is not obvious from a frame;
- Storybook story IDs for implemented states;
- explicit differences where code chooses responsive, accessible, or runtime
  behavior that a static frame cannot express.

Do not reproduce Figma layer trees or absolute coordinates mechanically. Do
not abandon Figma after implementation either: design changes update the
active frame/state inventory, while code changes update Storybook and tests.

Figma Variables can support automated synchronization, and Code Connect can
map published Figma library components to repository components. Adopt those
only when the Figma library is published, component identities are stable, and
the required Figma plan/access is available. Until then, DTCG remains the
numeric authority and the acceptance mapping is explicit in feature guides.

## Review evidence

Every frontend handoff states:

- owning layer and why;
- Figma frames/states reviewed and intentional differences;
- Storybook stories added or changed;
- Light, Dark, English, Simplified Chinese, keyboard, and narrow-width evidence;
- generated files and documentation changed;
- exact checks run;
- remaining visual debt or deferred integration.

Useful primary references: the
[DTCG token format](https://www.designtokens.org/TR/2025.10/format/),
[Figma Variables API](https://developers.figma.com/docs/rest-api/variables/),
[Figma Code Connect](https://developers.figma.com/docs/code-connect/),
[Storybook interaction testing](https://storybook.js.org/docs/writing-tests/interaction-testing),
[Storybook accessibility testing](https://storybook.js.org/docs/writing-tests/accessibility-testing),
and [Primer's design contribution workflow](https://primer.style/product/contribute/design/).
