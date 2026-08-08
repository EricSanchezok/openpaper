---
target: Scholens mobile composer and primary navigation integration
total_score: 24
max_score: 40
na_heuristics: ""
p0_count: 0
p1_count: 2
timestamp: 2026-08-05T13-25-12Z
slug: web-src-features-home-components-app-shell-tsx
---

# Scholens mobile bottom dock critique

## Design Health Score

| #         | Heuristic                       |     Score | Key issue                                                                                                   |
| --------- | ------------------------------- | --------: | ----------------------------------------------------------------------------------------------------------- |
| 1         | Visibility of System Status     |         3 | Activity states are clear, but the current research scope is hidden by the context icon.                    |
| 2         | Match System / Real World       |         3 | Research language is natural; the context icon still requires interpretation.                               |
| 3         | User Control and Freedom        |         3 | Stop, retry, clear context and new chat exist; failed-send draft recovery is unclear.                       |
| 4         | Consistency and Standards       |         3 | Tokens and controls are consistent, but the bottom area mixes floating-card and fixed-navigation materials. |
| 5         | Error Prevention                |         3 | Invalid and busy states are guarded; a failed send may still clear the draft.                               |
| 6         | Recognition Rather Than Recall  |         2 | Navigation labels are visible, but the default library scope must be remembered.                            |
| 7         | Flexibility and Efficiency      |         2 | Keyboard and context shortcuts exist; mobile scope switching is not explicit enough.                        |
| 8         | Aesthetic and Minimalist Design |         2 | The reading view is restrained, but the border, strong shadow and tab divider over-segment the bottom area. |
| 9         | Error Recovery                  |         2 | Retry UI exists; composer draft preservation needs stronger behavior.                                       |
| 10        | Help and Documentation          |         1 | The interface does not explain the context icon or unavailable destinations.                                |
| **Total** |                                 | **24/40** | **Acceptable; the bottom structure needs convergence before release.**                                      |

## Design Specificity Verdict

Scholens has product-specific content semantics through research activity,
references, context selection and reasoning strength. The mobile bottom shell is
still category-interchangeable: a floating AI-chat composer is stacked above a
separate three-item web navigation bar, while the most Scholens-specific state
-- the active research scope -- is hidden behind an icon.

The deterministic detector returned zero findings for `app-shell.tsx`,
`research-composer.tsx` and `conversation-view.tsx`. This is not a false
negative about token usage: the implementation correctly uses semantic colors,
spacing and elevation aliases. The defect is compositional. Browser geometry
confirmed that the composer is sticky inside `main`, while the tab bar is a
non-sticky sibling outside it.

No live visual overlay was produced. Mutable browser injection failed because
the Browser evaluator exposed a read-only document title. Evidence therefore
uses the fresh Storybook tab, runtime geometry, scroll measurements, the user's
390 x 844 screenshot and deterministic source lines.

## Overall Impression

The conversation itself feels calm and credible. The moment the user reaches
the thumb zone, the interface changes material language: a raised card ends,
a 12 px gap appears, a hard divider starts, and a second navigation surface
takes over. Yuanbao feels more natural because its composer and navigation are
children of one bottom material and one spacing rhythm, not because it merely
uses larger radii or smaller margins.

## What's Working

1. Touch targets are already strong: context and submit controls are 48 px, and
   tab items are 56 px tall.
2. Reading hierarchy is restrained and clear; activity, response and sources
   do not compete with the composer.
3. The composer remains reachable while scrolling, and auto-scroll behavior
   respects users who are reading older content.

## Priority Issues

### P1 — Composer and primary navigation live in different layout layers

The composer is sticky inside the scrollable `main`; the tab bar is outside it.
The composer's fade ends exactly where the tab bar begins, so spacing tweaks
cannot make them read as one unit.

Fix: create a mobile-only bottom dock owned by the shell. The composer slot and
tab bar should share one stacking context, surface, top fade, gutter and safe
area. Keep `main` as the only scroll container and reserve the dock's measured
height in the reading area. Preserve the current desktop sticky composer.

Suggested command: `$impeccable adapt`.

### P1 — Border and elevation express the same separation three times

The composer has a border plus `shadow-raised`, whose light-mode token resolves
to 40% black. The tab bar adds a top border. This makes a stable input base look
like a temporary overlay placed above another panel.

Fix: remove the tab divider and let the dock's subtle surface/fade establish the
region. Give the composer either a quiet border or a dedicated low-opacity
composer elevation token, not the shared raised-card treatment. Do not patch a
page-local shadow value.

Suggested command: `$impeccable quieter`.

### P2 — Spacing and safe area do not share one geometry

The composer uses 12 px horizontal padding, the tab bar uses 8 px, and the 12 px
gap between them belongs to neither visible surface. The tab bar alone consumes
the bottom safe area.

Fix: use one dock gutter (16 px at 390/430 px, 12 px at 320 px), place the gap
inside the shared dock surface, and consume `safe-area-inset-bottom` once at the
dock boundary.

Suggested command: `$impeccable layout`.

### P2 — The active research scope is visually absent

The default entire-library context is represented only by an `@` button. Users
can see reasoning strength but cannot see where Scholens will search.

Fix: replace the icon-only mobile context trigger with a compact scope pill such
as `@ 资料库`, `@ 3 篇`, or a truncated project name. Keep it in the same row and
avoid adding a permanently taller second row.

Suggested command: `$impeccable clarify`.

## Persona Red Flags

- Casey, a distracted mobile user, sees six thumb-zone targets split into two
  visual panels and must first infer whether they belong to one workflow.
- Jordan, a first-time user, cannot infer the active scope from `@`; disabled
  Library and Projects destinations can look broken rather than forthcoming.
- Sam, an assistive-technology user, benefits from the existing target sizes and
  labels, but the context control does not announce the current research scope.

## Minor Observations

- The mobile header bottom border and tab bar top border make the experience
  read as three webpage bands rather than one continuous conversation surface.
- The composer currently spans roughly 94% of the available content width; a
  shared 16 px dock gutter would feel calmer.
- The canvas fade stops at the exact structural boundary, amplifying the seam.
- A failed send can clear the draft because the composer resets after an
  `onSubmit` path that catches errors upstream.

## Questions to Consider

1. Is the bottom region a single research-workbench dock, or a floating input
   plus independent website navigation?
2. Should the active research scope be more visible than the current reasoning
   strength at the moment a user prepares a question?
3. If the composer is a stable daily-use base, should it visually behave like a
   raised dialog?

## Resolution — 2026-08-05

Resolved in the unified mobile Dock implementation:

- `AppShell` now owns one `MobileBottomDock` containing the single mounted
  Composer and primary navigation. Conversation and empty states no longer
  create separate sticky Composer layers.
- The tab divider and independent safe-area consumption were removed. The Dock
  owns its safe areas once, uses the approved 8 px content gutter, a 4 px
  internal gap, and a non-layout 20 px top fade.
- `elevation.composer` replaces the shared raised-card shadow on phones: 12%
  black in Light and the existing 40% overlay in Dark. Desktop retains
  `elevation.raised`.
- The context control announces and displays the active scope, truncating only
  its visible copy. The full scope remains in its accessible name.
- Soft-keyboard handling hides navigation and removes bottom safe-area padding;
  hardware keyboards do not change the Dock composition.
- The active primary destination now has an explicit semantic and visual state:
  `aria-current="page"`, a filled circular icon surface, inverse icon contrast,
  and stronger label weight. Inactive destinations keep the muted role, so the
  selected item is not communicated by color alone.

The earlier 16/12 px gutter suggestion was superseded by the approved 8 px
product contract after reviewing 320 px thumb targets and available input
width. The underlying issue—one shared geometry rather than mismatched local
padding—is resolved.
