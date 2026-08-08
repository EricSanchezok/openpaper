# 0009 — Conversation turns own response variants

Status: Accepted
Date: 2026-08-08
Owners: Scholens

## Context

A conversational user prompt can be regenerated, but a flat sequence of user
and assistant messages cannot represent which generated answer is selected,
which references belong to it, or when alternative branches stop being useful.
Encoding retry state in Web-only arrays would also make refresh, citations, and
future Reader conversations disagree with the Server.

## Decision

The persisted conversation aggregate is `ConversationTurn` plus one or more
`ConversationResponse` variants.

- A turn owns the immutable user prompt, context scope, reasoning strength,
  locale, time zone, and sequence.
- A response owns generation state, final content, ordered worklog trace,
  references, artifacts, and follow-up suggestions.
- The turn's `selected_response_id` identifies the only response used as Agent
  history and the response shown by default.
- Only the latest turn may create another response or select a completed
  response. A successful retry becomes selected atomically; a failed or
  cancelled retry leaves the previous selection unchanged.
- Creating the next turn first deletes the prior turn's unselected responses
  and clears suggestions that are no longer presented. Historical turns are
  therefore linear and bounded.
- Public creation routes are `/turns` and `/turns/{turn_id}/responses`. There is
  no `/messages` write route, compatibility DTO, or dual repository.
- Follow-up suggestions belong to one response variant and are generated only
  for the latest selected completed response. The Server claims generation,
  runs the model without an open database transaction, then revalidates the
  same ownership before persisting exactly three typed suggestions. A late
  result is discarded after the selection or latest turn changes.

References and research artifacts use `response_id`; they never attach to an
ambiguous generic message. The existing node-driven Agent harness remains the
authority for response item ordering and links to this decision for aggregate
ownership.

## Alternatives considered

- Keep Message rows and store variants in JSON. Rejected because relational
  ownership, selection, cleanup, and source integrity would remain implicit.
- Preserve every retry branch forever. Rejected because the product exposes
  switching only on the latest turn and old branches would create unbounded,
  invisible data.
- Model retries as new user turns. Rejected because it duplicates the prompt
  and corrupts conversation semantics and title generation.

## Consequences

Retry and response switching survive refresh and share one Server-enforced
latest-turn policy. Suggestions and sources naturally follow the selected
response. Starting a new turn intentionally removes old alternatives, so this
is not a branching-conversation history feature.

The change is destructive while Scholens is local-only. Existing development
conversation data is cleared before applying the schema; no migration adapter
or backward-compatible endpoint is maintained.

## Validation

Contract tests cover initial generation, retry success/failure/cancellation,
concurrent and non-latest conflicts, response selection, history projection,
cleanup when a newer turn is created, suggestion idempotency, and the
short-transaction generation boundary. The public OpenAPI snapshot and Web
types must contain no Message creation route or Message aggregate.
