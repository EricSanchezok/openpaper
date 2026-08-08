---
target: Home 聊天运行中与有消息后的页面
total_score: 17
max_score: 40
na_heuristics:
p0_count: 0
p1_count: 3
timestamp: 2026-08-05T05-22-43Z
slug: src-features-home-components-conversation-view-tsx
---

# Home conversation streaming critique

## Design Health Score

| #         | Heuristic                           |     Score | Key issue                                                                                                                  |
| --------- | ----------------------------------- | --------: | -------------------------------------------------------------------------------------------------------------------------- |
| 1         | Visibility of system status         |       2/4 | The disclosure header, its final history row, and a separate generic working line represent the same current state.        |
| 2         | Match between system and real world |       1/4 | Iteration counts, tool names, workspace labels, and English status strings expose implementation vocabulary.               |
| 3         | User control and freedom            |       2/4 | Stop and disclosure controls exist, but recovery actions are missing and automatic scrolling can fight history inspection. |
| 4         | Consistency and standards           |       1/4 | Progress, reasoning, provider warnings, cancellation, errors, and sources use disconnected presentation patterns.          |
| 5         | Error prevention                    |       2/4 | Duplicate sends are blocked, but infrastructure failure can be misrepresented as a successful no-results search.           |
| 6         | Recognition rather than recall      |       2/4 | Users must infer which raw rows are phases, retries, searches, warnings, or completion.                                    |
| 7         | Flexibility and efficiency          |       2/4 | Expansion exists, but experts receive volume rather than useful structured detail.                                         |
| 8         | Aesthetic and minimalist design     |       2/4 | The conversation canvas is calm, but expanded progress becomes a long diagnostic dump.                                     |
| 9         | Error recovery                      |       1/4 | Generic terminal copy loses structured error meaning and offers no adjacent retry or scope adjustment.                     |
| 10        | Help and documentation              |       2/4 | Rephrase/contact-support guidance is not tied to the actual failure state.                                                 |
| **Total** |                                     | **17/40** | **Poor: the visual foundation is usable, but the progress interaction model requires consolidation.**                      |

## Design Specificity Verdict

The visual restraint is coherent, but the interaction is category-interchangeable. Scholens' distinctive value—research scope, evidence gathering, source quality, and grounded conclusions—appears only as raw backend telemetry rather than an authored research interaction language.

The deterministic detector reported zero findings for `conversation-view.tsx`. This is not evidence that the experience is healthy: the important defects are state accumulation, repeated semantics, mixed-locale server copy, dynamic announcement behavior, and long-stream growth, which are outside the detector's static rules.

Browser inspection of the Storybook Processing state confirmed that the disclosure button repeats its own status inside the expanded history while a separate `role=status` line displays another generic progress message. At 390px there was no horizontal overflow, but the sticky composer consumed much of the viewport. Mutable overlay injection was blocked by the browser URL security policy, so no user-visible overlay was produced.

## Overall Impression

The current page has a good calm base, stable composer, and correct instinct toward transparent progressive disclosure. Its biggest problem is semantic, not decorative: one internal operation is presented three times, while diagnostic text is mistaken for user-facing research progress.

## What's Working

- The central reading column and bottom composer make the conversation easy to scan.
- The disclosure is a native button with `aria-expanded`, and Stop remains available during streaming.
- Progress history survives reloads, which can support trust once the history is curated.

## Priority Issues

### P1 — Competing progress representations

The latest status is the disclosure heading, repeats as the last history item, and sits above a generic localized working line. Replace all three with one `Agent activity` row inside the assistant turn. It owns live phase, history, completion, cancellation, partial success, and failure. Suggested command: `$impeccable distill`.

### P1 — Backend telemetry is used as product copy

`iteration 5`, title-cased tool names, workspace labels, generated queries, provider names, and raw English strings are implementation concepts. The primary interaction should use four localized phases: understanding the question, searching the active scope, reviewing evidence, and preparing the answer. Repeated searches should aggregate; raw technical trace, if retained, belongs behind tertiary technical details. Suggested command: `$impeccable clarify`.

### P1 — Failure, no-results, and partial success are conflated

A provider outage can coexist with a no-results answer, which incorrectly blames the user's query. Define explicit outcomes: `complete`, `partial`, `no_results`, `error`, and `cancelled`, with Retry or Adjust scope where appropriate. Suggested command: `$impeccable harden`.

### P2 — Expanded history is unstructured and can fight the reader

Long runs expose many identical bullets, while every status/content update can smooth-scroll the page. Group history into at most four phases, aggregate repeated work, preserve manual expansion and scroll position, and respect reduced motion. Suggested command: `$impeccable distill`.

### P2 — Storybook does not cover the state contract

The current Processing story covers only one status and Stop. Add long expanded history, mixed-language/long content, completion, partial failure, no results, terminal error, cancellation, reasoning with sources, and narrow-width states. Suggested command: `$impeccable harden`.

## Recommended collapsed/expanded state model

| Outcome    | Collapsed                                                                                                 | Expanded                                                                                     |
| ---------- | --------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Streaming  | Activity indicator plus one localized present-tense phase; entire row is the disclosure.                  | Three or four semantic phases with completed/current semantics; repeated searches aggregate. |
| Complete   | Muted check plus `研究完成 · 使用 N 个来源` when the count is reliable; omit for trivial no-tool answers. | Concise completed phases, active scope, and a jump to visible sources.                       |
| Partial    | Warning plus `部分资料源不可用；已使用其余来源完成回答`.                                                  | Explain the unavailable capability in user terms and what evidence remained.                 |
| No results | Neutral search state plus `未找到相关资料`.                                                               | Show searched scope and actions to adjust scope or rephrase.                                 |
| Error      | Warning/error plus `未能完成检索`; expanded by default when action is required.                           | Plain-language cause, preserved work, Retry, and Adjust scope.                               |
| Cancelled  | Neutral stop state plus `已停止`.                                                                         | Preserve completed phases and offer restart where appropriate.                               |

The user's proposed thin single-line expandable pattern is the correct direction, provided it replaces both existing progress elements and becomes a complete turn-state component rather than a styled text link.

## Persona Red Flags

**Jordan, first-time user:** `iteration 5` looks like a stuck loop; English technical text interrupts the Chinese experience; provider failure followed by no-results gives no trustworthy next action.

**Sam, screen-reader and keyboard user:** the meaningful changing status is not the live region; the static generic line is. Expanded history lacks programmatic current-step semantics, and frequent smooth scrolling has no reduced-motion branch.

**Riley, stress tester:** long runs grow without bounds or grouping; recoverable failure, fallback, no-results, and terminal error are indistinguishable; generated queries and diagnostics may expose more research intent than the primary interface should show.

## Minor Observations

- The `S` avatar is generic and redundant beside the Scholens label, but it is low priority and can later become a real brand mark.
- Reasoning should not be mixed into an execution-log hierarchy; if retained, expose a concise user-legible approach, not raw model reasoning.
- Search phrases can be valuable to researchers only as cleaned, grouped secondary details such as `搜索了 11 个相关主题`.
- The current calm visual language should be preserved; this needs semantic hierarchy, not more decoration.

## Questions to Consider

- If an iteration count does not help a researcher make a decision, why is it outside observability logs?
- Should the activity row name the active scope, such as `正在检索“思维链压缩技术”项目中的 12 篇论文`?
- What evidence threshold permits partial success when one provider fails?
- Can every Scholens conversation surface share the same phases and five terminal outcomes?

## Resolution update — 2026-08-08

The single activity disclosure and typed Agent trace remain the canonical
progress model. Terminal stream failures now retain their safe public code,
kind, retryability, correlation ID, and diagnostic ID instead of collapsing to
`Could not complete`. Redis capacity outages are classified as unavailable
rather than as user rate-limit exhaustion, while the failed user message stays
in history for an explicit, idempotent retry. Raw dependency details remain in
controlled diagnostics only.
