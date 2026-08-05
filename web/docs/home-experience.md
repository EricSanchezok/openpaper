# Home Experience

Home is the first production slice of the replacement frontend. Its canonical
design is the Figma page `20 — Home`, including the default workspace, collapsed
sidebar, context picker, recent content, and conversation states. Figma owns
visual hierarchy and acceptance; this document records runtime ownership and
the deliberately deferred boundaries.

## Entry and ownership

- `/` requires an authenticated session. Anonymous visitors are sent to
  `/login` with a safe return target.
- The selected conversation is shareable navigation state and therefore lives
  in `?conversation=<uuid>`. A refresh restores that conversation.
- Conversations, papers, projects, and message history are server state owned
  by TanStack Query. Composer input uses React Hook Form and Zod; its form state
  is owned by `HomeWorkspace` so responsive composition changes never discard
  an unsent draft. Sidebar, picker, and in-progress stream state remain local.
- Desktop and mobile share one navigation model, actor state, conversation
  state, and `AppShell` boundary, but use device-appropriate compositions. The
  desktop sidebar is 264 px when expanded and 72 px when collapsed. Phones use
  a persistent bottom bar for Ask, Library, and Projects. Their full-width
  navigation hub is reserved for conversation search, pinned/recent history,
  and the account trigger anchored above the bottom safe area; it does not
  repeat the primary destinations or render the desktop Sidebar inside a
  narrow drawer. The hub closes with a directional collapse control rather
  than a dismiss-style X.
- Collapsing the desktop sidebar changes only its horizontal geometry. The top
  control, navigation rows, and account trigger retain their vertical anchors.
- Deferred destinations retain their product names in the visible navigation;
  availability is disclosed through the disabled control and its tooltip, not
  implementation-plan copy.

## Data and streaming

Home consumes only the public conversation, project, library-paper, and actor
contracts. It does not import from `client/` and does not define duplicate wire
DTOs.

Conversation creation and continuation use one standard SSE decoder. The
stream accepts `start`, `activity`, `content_delta`, `references`, `complete`,
and `error`. `activity` is an ID-addressed, sanitized tool lifecycle record;
the interface derives localized progress copy from its category and state.
Model reasoning, provider heartbeats, raw tool names, arguments, and return
payloads are not product UI. `complete` and `error` are terminal. The user may
abort an active stream; the Web app never automatically retries message creation.
After completion, only the active conversation, its messages, and the
conversation list are invalidated.
The Server replaces the default Sidebar title once after the first successful
assistant reply. Follow-up turns do not regenerate it, and user renames are
never overwritten by title generation.

## State coverage

| Surface      | Deterministic coverage                                                                |
| ------------ | ------------------------------------------------------------------------------------- |
| Home data    | populated, loading/slow, empty, and recoverable error                                 |
| Navigation   | expanded, collapsed, mobile bottom bar and history hub, search, active conversation   |
| Context      | entire library and selected project/paper sources, including search                   |
| Conversation | direct answer, tool activity, partial failure, references, complete, cancelled, error |
| Presentation | English, Simplified Chinese, Light, Dark, 1440 px, 390 px, and 320 px overflow check  |

The Figma conversation-state frames and Storybook stories map one-to-one:

| Figma `20 — Home` state    | Storybook acceptance state                    |
| -------------------------- | --------------------------------------------- |
| Direct answer              | `Conversation View / Direct Answer`           |
| Thinking before tools      | `Conversation View / Thinking Without Tools`  |
| Single tool running        | `Conversation View / Single Tool Running`     |
| Multiple tools expanded    | `Conversation View / Multiple Tools Expanded` |
| Partial tool failure       | `Conversation View / Partial Failure`         |
| Completed activity summary | `Conversation View / Multiple Tools Expanded` |
| Cancelled                  | `Conversation View / Cancelled`               |
| Error                      | `Conversation View / Error`                   |

The mobile Dock acceptance inventory extends that mapping:

| Figma `20 — Home / Mobile` target | Storybook acceptance state                  |
| --------------------------------- | ------------------------------------------- |
| Empty + Dock / Ask selected       | `Workspace / Mobile Empty`                  |
| Conversation + Dock               | `Workspace / Mobile Conversation`           |
| Keyboard Open                     | `Workspace / Mobile Keyboard Open`          |
| Library scope                     | `Research Composer / Library Scope`         |
| Multiple-paper scope              | `Research Composer / Multiple Papers Scope` |
| Long project scope at 320 px      | `Research Composer / Long Project Scope`    |
| Multiline input                   | `Research Composer / Multiline Input`       |
| Streaming / Stop                  | `Research Composer / Streaming Stop`        |
| 430 px Dark English               | `Research Composer / Dark English Large`    |

The mobile acceptance set is synchronized to the active `20 — Home` Figma
page. Its primary navigation state uses the shared action surface and inverse
icon roles for the current destination, while inactive destinations retain the
muted semantic role. Each future destination must supply its own
`aria-current="page"` state when its vertical slice becomes available; Home
does not create placeholder routes merely to demonstrate those states.
The selected-state specimens are the node-specific
[Ask](https://www.figma.com/design/2T5BuTPMIrM2jsVhgIVYIX/Scholens-%E2%80%94-Product-Design?node-id=882-3416),
[Library](https://www.figma.com/design/2T5BuTPMIrM2jsVhgIVYIX/Scholens-%E2%80%94-Product-Design?node-id=882-3437),
and
[Projects](https://www.figma.com/design/2T5BuTPMIrM2jsVhgIVYIX/Scholens-%E2%80%94-Product-Design?node-id=882-3458)
frames. Library and Projects document the future selected visual state only;
their runtime destinations remain deliberately unavailable in the Home slice.

The former heavy process card is archived in Figma and is not a supported Web
state. `Conversation View / Narrow Long Subject` and
`Conversation View / Simplified Chinese Dark` supplement the Figma mapping with
runtime overflow, locale, and appearance coverage. Optimistic and persisted
messages are reconciled by `turn_id`; the isolated deduplication state guards
against showing the same user message twice while a stream is active.

On phones, the shell uses a 64 px content bar plus platform safe-area insets.
The bar owns navigation, the current reasoning-strength selector, and the
new-chat action. The selector exposes only Standard and Deep; model selection
is not part of the Scholens product surface. Conversation content uses a larger
reading scale and touch-sized activity disclosure and source rows. A single
`MobileBottomDock` owns the Composer, primary navigation, horizontal safe-area
gutters, bottom safe area, and stacking layer. The Composer and navigation are
separated by 4 px inside the Dock rather than behaving as independent floating
surfaces; a non-layout 20 px fade softens the transition from scrolling content.
Only one real Composer is mounted at a time. The composer starts as a
single-line input row, grows with the user's text, and keeps context and submit
controls in the thumb zone without repeating reasoning controls inside the
input surface.
The mobile scope trigger is a dynamic pill. It names the entire library, a
single project or paper, multiple papers, a mixed item count, or the empty
selection; visible titles may truncate, while the accessible name always
contains the full scope. The separate selected-source chip remains desktop-only.
Every scope, send, stop, and navigation target remains at least 48 px.
The current bottom-navigation destination is represented by both
`aria-current="page"` and a filled circular icon surface, with a stronger label.
This state is not color-only: shape, weight, and semantics remain distinguishable
in monochrome, Dark appearance, and high-contrast environments.

While the Composer is focused, the shell combines `visualViewport` occlusion
with the layout viewport to distinguish a soft keyboard from a hardware
keyboard. A soft keyboard hides the three-item navigation, removes the Dock's
bottom safe-area padding, and constrains the shell to the visible viewport so
the Composer stays above the keyboard. Closing it restores navigation and the
safe area without changing the message scroll position. Browsers without
`visualViewport` fall back to hiding navigation while the mobile Composer is
focused.
Markdown is rendered as semantic headings, lists, links, code, and
horizontally scrollable tables; raw HTML is not accepted. The same messages,
stream reducer, context state, and submission logic are used by desktop and
mobile.

The mobile visual baseline is represented by `Home / Workspace / Mobile Empty`,
`Mobile Composer Expanded`, `Mobile Conversation`, `Mobile Conversation Large`,
`Mobile Reasoning Menu Open`, `Mobile Navigation Open`, and `Mobile Processing`, plus
`Conversation View / Mobile Research Answer` in Light and Dark. The acceptance
set covers 390 x 844 and 430 x 932; 320 x 568 is an overflow and
minimum-usability check rather than the primary aesthetic target.

When both recent-paper and recent-project queries settle empty, Home uses a
focused first-run composition instead of preserving empty card silhouettes.
On phones, its composer sits at the bottom of the usable canvas immediately
above primary navigation; the research prompt remains in the available reading
area rather than pulling the input toward screen center. On desktop, the 760 px
composer retains the centered Figma composition. Its textarea delegates focus
presentation to the rounded composer boundary, so native rectangular outlines
never split the composition.
The account trigger sits against the sidebar's bottom safe-area inset without a
redundant disclosure arrow. Its menu aligns to the expanded sidebar content
edge and opens to the right of the collapsed rail.
When only one collection has data, only that section is rendered and centered.
Loading and recoverable errors remain visible per collection. The populated
state continues to follow the canonical two-paper/three-project Figma layout.

The visual acceptance pass also includes a 2560 px wide viewport so the
first-run composition remains intentional on large desktop displays.

Storybook is the isolated state catalog. Playwright covers authenticated route
composition, the context interaction, accessibility, locale selection, and
narrow-screen containment. The real local Server remains the final integration
check.

## Deferred by design

Library, Projects, Reader, Translation, and Settings routes remain disabled
navigation destinations until their own vertical slices begin. Home does not
introduce abstractions for those pages, edit conversation metadata, or add a
legacy-client compatibility layer. Any newly discovered backend gap must block
a current Home behavior before the contract is expanded.
