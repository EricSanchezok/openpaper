# Design Tokens and Figma Workflow

## Authority and flow

The token graph mirrors the Figma architecture:

```text
DTCG primitives
  -> theme palette aliases
  -> Light/Dark semantic aliases
  -> generated CSS variables and TypeScript metadata
  -> Tailwind semantic utilities
  -> components
```

Current source files:

```text
src/design-system/tokens/
├── primitives.json
├── themes/default.json
├── semantic/light.json
├── semantic/dark.json
├── effects.json
└── dimensions.json

src/design-system/adapters/
└── tailwind.json
```

Figma is used to explore and validate visual intent. After initial calibration,
the DTCG files in this repository are the numeric source of truth. Do not edit
files under `src/design-system/generated` by hand.

## Token layers

- **Primitives** contain raw values and have no component meaning.
- **Theme palette** maps stable palette slots to primitives. A future Ocean
  theme changes this layer rather than component styles.
- **Semantic tokens** describe purpose: canvas, surface, text, border, action,
  focus, selection, feedback, annotation, and elevation.
- **Composite effects** assemble semantic colors and geometry into reusable
  elevation recipes.
- **Framework adapters** expose stable utility names; they do not own values.
- **Component styles** consume semantic tokens only.

Do not alias semantic tokens to other semantic tokens. Both Light and Dark map
directly to the theme palette so the graph remains inspectable.

## Editing workflow

1. Identify whether the change is primitive, theme, semantic, or component
   level. Prefer the highest meaningful layer; do not change a primitive to fix
   one component.
2. Update the relevant DTCG source using `$type`, `$value`, and references.
3. Run `pnpm tokens:build`.
4. Run `pnpm design:check` to validate appearance parity, references, adapter
   aliases, and forbidden styling shortcuts.
5. Inspect Light and Dark stories, focus, disabled, feedback, overlay, and long
   content in Storybook.
6. Run `pnpm tokens:check`, tests, and builds.
7. Commit the DTCG source and generated output together.

`tokens:check` regenerates into a temporary directory and fails if committed
outputs drift. Manual edits to generated CSS or metadata therefore fail CI.

## Using tokens in components

Use semantic Tailwind names generated from the adapter, for example
`bg-canvas`, `bg-surface`, `text-foreground`, `text-muted`, `border-line`, and
`bg-primary`, plus `text-ui`, `text-caption`, `shadow-overlay`, and
`shadow-composer`. `elevation.composer` is the mobile input-surface lift: it
uses the shared 0/6/20/-10 geometry with a 12% black Light shadow and the
existing 40% overlay in Dark. Desktop Composer surfaces retain
`elevation.raised`. If a
necessary semantic role does not exist, add and document the role instead of
writing hex, RGB, HSL, a primitive palette value, or a repeated arbitrary
recipe at the call site.

The Tailwind `@theme` adapter is appended to generated `dimensions.css`. Add or
rename an alias in `src/design-system/adapters/tailwind.json`; never recreate an
`@theme` table in global CSS.

Interactive descendants inherit the state of their shared control. In
particular, an icon inside a disabled button resolves to the shared disabled
icon role even when its enabled state is inverse. Composite controls may
suppress a native child's outline only when the containing control exposes an
equivalent focus-visible state using semantic control or focus tokens. Mark
that child with `data-focus-delegate`; this is the shared contract that keeps
the global focus fallback from drawing a second, rectangular focus surface.
Ordinary interactive elements consume the shared `keyboardFocusRing` utility;
its one-pixel semantic ring is the only approved product focus recipe. Global
CSS owns only delegated text-control focus. It must not restore a broad native
outline fallback that can turn composite disclosures into thick black or white
rectangles.

Disabled prominence is also semantic. If a disabled primary action disappears
into a canvas in one appearance, adjust `color.action.disabled-*` for that
appearance and review every disabled-button story. Do not patch the individual
button or feature call site.

Allowed raw-color exceptions are limited to source images, PDF content, and
third-party brand marks that must preserve their identity. The surrounding UI
still uses semantic tokens.

## Runtime contract

```html
<html data-theme="default" data-color-scheme="light"></html>
```

- Theme preference key: `scholens-theme`.
- Appearance preference key: `scholens-color-scheme`.
- Appearance preference values: `system`, `light`, or `dark`.
- Preferences are stored in localStorage and cookies.
- The inline initialization script resolves appearance before paint.

Theme and Appearance remain independent. Adding Ocean must not create combined
`Ocean Light` and `Ocean Dark` mode names.

## Adding a theme

1. Add `tokens/themes/<theme>.json` using the same palette slots as Default.
2. Add semantic outputs for that theme and both appearances without changing
   component token names.
3. Extend `build-tokens.mjs` and generated `themeNames` metadata.
4. Add the Theme option to Storybook while keeping Appearance independent.
5. Validate all component stories and representative feature compositions.
6. Sync the matching Figma Theme mode and verify its aliases.

Do not add a new theme until all semantic roles resolve in both appearances.

## Figma synchronization

For a design-led change:

1. Explore the palette or semantic mapping in Figma Theme Lab.
2. Agree on token names and behavior, not frame coordinates.
3. Apply final numeric values to DTCG and generate code artifacts.
4. Update Figma from the agreed token data rather than independently tweaking
   copies of screens.
5. Validate canonical Figma frames against Storybook/implementation.

Code may use a robust Radix or Scholens component instead of copying a Figma
layer tree exactly. Layout hierarchy, density, state meaning, and visual intent
must remain consistent.
