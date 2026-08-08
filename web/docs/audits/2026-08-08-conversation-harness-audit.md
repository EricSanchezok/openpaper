# Conversation harness audit — 2026-08-08

## Scope and method

The audit covered the Pydantic AI node loop, tool lifecycle projection,
grounded-answer parsing, runtime-to-SSE adapter boundary, persistence and
idempotent replay, generated OpenAPI contract, Web stream decoder and reducer,
worklog grouping, Storybook states, and the architecture tests that prohibit
the former conversation loop. Static searches were combined with targeted
runtime/contract tests, Ruff, mypy, Web unit and Storybook tests, generated
artifact checks, and the complete Server and Web gates.

## Findings and remediation

| Finding                                                                   | Risk                                                                          | Resolution                                                                                                             |
| ------------------------------------------------------------------------- | ----------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Runtime emitted ad-hoc dictionaries which the adapter parsed again        | Silent field loss and two event protocols drifting independently              | Runtime now emits the public Pydantic event models directly plus one private typed terminal result                     |
| Citation-only text could start and complete an empty assistant item       | Blank worklog rows, invalid persisted responses, reducer dead branches        | Public items start only after visible text and completed item content is contractually non-empty                       |
| Pre-tool prose could exceed the persisted progress limit                  | A valid model response could fail only after its text had streamed            | One runtime helper bounds progress to 4,000 characters before completion and trace persistence                         |
| A run could reach persistence without a final visible answer              | Empty response variants and misleading successful terminal events             | Runtime rejects hidden-only output and the adapter independently requires final content before completing the response |
| Trace discriminator defaults were omitted during repository serialization | The answer streamed successfully but persistence failed, producing `未能完成` | Repository serialization now retains required `kind` discriminators and has a round-trip regression test               |
| Composer reset waited for the full request to finish                      | Submitted text stayed in the input while Stop was active                      | The accepted optimistic turn clears the Composer immediately; preflight failures still preserve the draft              |
| Web retained an empty-progress compatibility branch                       | Dead behavior contradicted the new non-empty public contract                  | The branch was deleted; generated types and reducers follow one destructive contract                                   |

## Resulting invariants

- Provider response boundaries and tool-call finish state classify assistant
  items; no prose matching or chain-of-thought parsing is used.
- One sequence orders safe progress and tool activity. Activity updates retain
  their ID and sequence.
- Only visible non-empty text can enter an assistant item. Only a final item can
  publish references or become `ConversationResponse.content`.
- The Server owns event validation, progress bounds, citations, persistence,
  idempotency, and the unique terminal result. Web owns presentation state and
  ignores events after a terminal state.
- The SSE decoder accepts only discriminators from the generated public union
  and stops dispatching after the first terminal event.
- Raw reasoning, heartbeat data, tool identity, arguments, and results remain
  outside the public contract.
- There is no legacy SSE reader, trace union, compatibility adapter, feature
  flag, duplicate reducer, or import from `client/`.
- Response retry reuses the same `LiveTurn` reducer and transcript position as
  initial generation. Suggestion pending and failed states project the
  persisted response status directly; neither feature introduces a parallel
  state machine or client-only retry loop.

## Dead-code and duplication audit

Repository searches found no runtime references to the removed
`ConversationToolLoop`, `finish_tool_use`, `run_stream_events`,
`FinalResultEvent`, `END_OF_STREAM`, old public `content_delta`, iteration
prompts, or the checklist activity UI. Remaining `tool_name` occurrences belong
to internal catalog, dispatch, analytics, and invocation-journal ownership and
are intentionally not public UI data.

The Home worklog remains feature-owned because it has only one real consumer.
It should move to a shared conversation package only when Project or Reader
introduces a second concrete consumer; extracting it earlier would create an
unproven abstraction.

Storybook exercises the complete response lifecycle: direct completion,
latest-only actions, multiple response variants, historical control removal,
retry streaming and failure, suggestion pending/completed/failed, sources,
ordered progress, partial failure, cancellation, and terminal error. These
states are fixtures over production types rather than mock-only component
branches.

The Figma audit also removed the two obsolete Reader conversation-only frames
from the active `50 — Reader` page. The replacement Reader contract explicitly
reuses Home message semantics and varies only the paper or selection scope, so
future Reader implementation has one product contract rather than a second
worklog, action, or evidence system.

## Residual risks and extension rules

- Provider SDK event shapes remain an upstream dependency. New providers need
  node-boundary contract tests before adoption; do not add provider-specific
  public events.
- The 4,000-character progress bound is a safety ceiling, not a copy target.
  Agent instructions and UI grouping should continue to favor short stage
  updates.
- Historical local response rows with invalid or empty assistant content are not
  supported by a compatibility layer. Local development may clear them; a
  future production migration would require an explicit data decision.
- New activity categories or assistant phases require a deliberate public
  contract change, regenerated types, reducer exhaustiveness, Storybook states,
  and an update to ADR 0008 in the same commit.
