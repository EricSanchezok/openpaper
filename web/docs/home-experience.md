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
  by TanStack Query. Composer input uses React Hook Form and Zod. Sidebar,
  picker, and in-progress stream state remain local.
- Desktop and mobile compose one `AppShell`. The desktop sidebar is 248 px when
  expanded and 64 px when collapsed; narrow screens expose the same navigation
  through a Sheet.

## Data and streaming

Home consumes only the public conversation, project, library-paper, and actor
contracts. It does not import from `client/` and does not define duplicate wire
DTOs.

Conversation creation and continuation use one standard SSE decoder. The
stream accepts `start`, `status`, `reasoning`, `content_delta`, `references`,
`complete`, and `error`. `complete` and `error` are terminal. The user may abort
an active stream; the Web app never automatically retries message creation.
After completion, only the active conversation, its messages, and the
conversation list are invalidated.

## State coverage

| Surface      | Deterministic coverage                                                               |
| ------------ | ------------------------------------------------------------------------------------ |
| Home data    | populated, loading/slow, empty, and recoverable error                                |
| Navigation   | expanded, collapsed, mobile drawer, active conversation                              |
| Context      | entire library and selected project/paper sources, including search                  |
| Conversation | history, processing, reasoning, content, references, complete, cancelled, and error  |
| Presentation | English, Simplified Chinese, Light, Dark, 1440 px, 390 px, and 320 px overflow check |

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
