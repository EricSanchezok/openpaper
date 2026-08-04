# Frontend governance audit — 2026-08-04

## Scope and method

The audit covered `web/src`, token sources and generated artifacts, Tailwind
integration, component boundaries, Storybook configuration/stories/MSW,
frontend tests, Figma page/state structure, and the repository development and
product guides. Static searches were combined with the existing architecture
gate, Storybook browser tests, build output, and local rendered-state checks.

## Baseline findings

The frontend was not yet a broad maintenance problem. It already had strong
foundations:

- no product-component hex/RGB/HSL colors outside token sources/generated
  output;
- one Iconoir-based icon system and no legacy-client imports;
- DTCG primitive → palette → Light/Dark semantic color layers;
- request-free UI/feedback primitives and vertical Authentication/Home slices;
- 25 deterministic Storybook files with theme, appearance, locale, network,
  data, viewport, MSW, browser interaction, and axe controls;
- generated OpenAPI types, architecture checks, and fixed local ports.

The material drift risks were:

| Risk before remediation                                  | Severity | Evidence                                                                        | Resolution                                                                    |
| -------------------------------------------------------- | -------- | ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Tailwind semantic bridge manually duplicated token names | High     | `globals.css` contained the complete alias table and one self-referencing alias | Generated adapter + self-reference check                                      |
| Light/Dark shape was convention, not a checked invariant | High     | Token build could succeed with a missing semantic role                          | Exact path/type parity in `design:check`                                      |
| Repeated 11px/13px typography literals                   | Medium   | Home shell, context picker, and conversation UI                                 | `type.caption` / `type.ui` tokens                                             |
| Repeated shadow recipes                                  | Medium   | Select, Popover, Dropdown, Toast, Dialog, Sheet, Home                           | DTCG composite elevation tokens                                               |
| Theme shortcuts could reappear                           | Medium   | Raw-color check covered only part of CSS color syntax                           | Expanded raw-color, `dark:`, primitive-var, `!important`, and sRGB-mix checks |
| Figma/Storybook lifecycle was implicit                   | Medium   | Good page/state coverage but no canonical add/change/delete workflow            | Frontend governance guide + checklist                                         |
| Web README implementation status had drifted             | Low      | Home described as unimplemented                                                 | Documentation corrected                                                       |

Figma inspection confirmed that the current product file is a multi-page,
state-rich acceptance source rather than only a cover. The Reader page alone
contains desktop/collapsed navigation, context, ask, annotation, search, and
process states. The remaining risk is traceability: feature guides need stable
node-specific acceptance links and Storybook story mappings as each slice is
implemented.

The active page taxonomy already separates Foundations, Components, Theme Lab,
Brand Lab, Authentication, Home, Library, Projects, Project Detail, Reader,
Translation, five Settings areas, and archived interaction states. That is a
sound design-side boundary. Code should preserve those product concepts without
copying the frame/layer hierarchy or creating empty route abstractions before a
vertical slice begins.

## External-practice conclusions

- The stable DTCG format supports typed tokens, groups, aliases, and composite
  shadows, matching a repository-owned token graph.
- Storybook treats stories as browser test cases; `play` functions, axe, and
  visual snapshots complement rather than replace Figma acceptance.
- Figma Variables and Code Connect can improve synchronization, but automated
  write/publish workflows depend on the Figma plan and a stable published
  component library. They are not prerequisites for a disciplined first-party
  workflow.
- Mature systems such as Primer require contributors to audit existing patterns
  and choose the correct system layer before introducing a new one.

## State after remediation

- 52 semantic color tokens exist in both appearances with checked parity.
- Tailwind aliases, two compact typography roles, and four elevation roles are
  generated and drift checked.
- Every implemented feature retains a Storybook state catalog; required global
  review axes and axe enforcement are checked.
- The design-system contract runs in the Web CI job rather than relying on
  local convention or reviewer memory.
- Add, change, delete, Figma handoff, Storybook evidence, and token workflows
  are documented and linked from the mandatory agent entry point.

## Residual, non-blocking work

- Hosted pixel-diff baselines are not configured. Storybook browser/a11y tests
  and local Figma comparison remain required; add Chromatic or an equivalent
  only with an owned project/token and an agreed baseline-review policy.
- Code Connect is deferred until Figma library components are published, code
  component identities stabilize, and the workspace has the required Dev/Full
  seat on an Organization or Enterprise plan. The current account cannot query
  published Code Connect components under that plan requirement.
- Future feature guides must add their own node-specific Figma → Storybook
  acceptance tables; inventing IDs before implementation would itself create
  stale metadata.
