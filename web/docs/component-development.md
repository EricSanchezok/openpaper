# Component Development

## Classify before creating

Place a component according to the language and dependencies it owns:

| Kind                      | Location                            | May contain product vocabulary? | May request data?         |
| ------------------------- | ----------------------------------- | ------------------------------- | ------------------------- |
| Design-system primitive   | `src/components/ui`                 | No                              | No                        |
| Async/empty-state pattern | `src/components/feedback`           | Only through props              | No                        |
| Product component         | `src/features/<feature>/components` | Yes                             | Prefer data passed in     |
| Route composition         | `src/app` or feature `routes`       | Yes                             | Through feature API layer |

Sidebar, Composer, ConversationMessage, PaperRow, ProjectCard, and Reader tools
are product components, not UI primitives. A component is not promoted merely
because two mockups look similar; promote it when its semantics and behavior are
actually shared.

## Component API rules

- Prefer semantic props such as `tone`, `size`, `loading`, and `invalid` over
  visual props such as `gray`, `rounded12`, or `left4`.
- CVA owns finite visual variants. Call-site `className` is for layout and rare
  composition, not for redefining a component's states.
- Support controlled and uncontrolled usage only when both are real needs.
- Forward native attributes and refs when the underlying control supports them.
- Preserve native semantics; never make a clickable `div` imitate a button.
- Loading controls retain their accessible name and prevent duplicate actions.
- Disabled and read-only are distinct states.
- Destructive actions use explicit language and `AlertDialog` when confirmation
  is necessary.

## Visual and interaction rules

- Consume semantic Tailwind utilities backed by generated variables.
- Never write product colors directly in a component.
- Use the Scholens `Icon` wrapper with Iconoir glyphs. Do not import another
  icon library or manually redraw a glyph inside product code.
- Every interactive control must have default, hover, pressed, focus-visible,
  disabled, and loading behavior where applicable.
- Icon-only controls require an accessible label and usually a Tooltip.
- Narrow containers and long English or Simplified Chinese content must not
  break layout.
- User-visible product copy uses `next-intl` message keys. Do not concatenate
  translated fragments or hardcode fallback English inside product components.
- UI primitives remain language-agnostic. Callers provide labels and content;
  a primitive translates only a universal default that it explicitly owns.
- Motion must explain state or spatial continuity and respect reduced-motion;
  decorative motion requires a product reason.

## External component intake

Before accepting external source code:

1. Check license, maintenance activity, React/Next SSR compatibility, keyboard
   behavior, and accessibility.
2. Confirm Radix cannot already provide the required primitive.
3. Place the source in the correct UI or feature boundary.
4. Replace its colors, spacing, type, icons, global CSS, and portals with
   Scholens conventions.
5. Remove bundled themes and overlapping primitive/icon dependencies.
6. Add stories, interaction tests, dark appearance, narrow-container coverage,
   and axe checks.

shadcn/ui is a source distribution mechanism, not a runtime design dependency.
Imported source becomes Scholens-owned code and follows this handbook.

## Storybook contract

Stories are executable component states, not a screenshot gallery. A new
interactive component normally includes:

- Default and all meaningful variants/states.
- Light and Dark appearance verification through the global toolbar.
- Long/localized content and Narrow panel coverage.
- Keyboard interaction in a `play` function.
- Loading, empty, error, slow, or offline behavior when relevant, using MSW.
- No serious or critical axe violations.

Keep stories beside their component or feature. Use deterministic fixtures;
stories must not depend on the FastAPI process or a developer account.

## Definition of done

- The component is in the correct boundary and has no forbidden imports.
- Its public props express behavior rather than one screen's geometry.
- Semantic tokens and the Icon wrapper are used consistently.
- Keyboard, focus, disabled, loading, error, long-content, and narrow behavior
  are covered as applicable.
- Storybook and automated tests pass in Chromium.
- Product-specific behavior is not duplicated in a second feature.
