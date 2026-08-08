# ADR 0008: One node-driven conversation agent with ordered public items

- Status: Accepted
- Date: 2026-08-05

## Context

The former Conversation runtime forced every request through a tool-selection
model call and then a separate final-answer call. Its public stream exposed
free-text status, model reasoning, provider heartbeats, and internal iteration
labels. Ordinary questions therefore attempted paper retrieval, while clients
had to interpret an unstable diagnostic trace.

Home, projects, and papers also need one coherent conversational capability.
Their context should guide the same agent rather than create independently
maintained runtimes.

## Decision

Use one Pydantic AI agent loop for every Conversation scope.

- Pydantic AI owns model turns, tool-call continuation, and model event decoding.
- Scholens dynamically supplies only the tools authorized by the canonical
  `ToolCatalog` and routes every invocation through `ToolDispatcher` or the
  connector resolver.
- Scholens retains permission checks, operation provenance, idempotency,
  source validation, citation materialization, persistence, budgets,
  cancellation, logging, and token settlement.
- Requests carry a locale and validated IANA time zone. An injectable Clock
  supplies absolute local time to the model.
- Scholens consumes the run through Pydantic AI `Agent.iter()` node boundaries.
  A `ModelRequestNode` streams one provisional assistant item. The complete
  `ModelResponse` and following `CallToolsNode` classify it as user-visible
  `progress` or the accepted `final` answer; no natural-language phrase parser
  participates in classification.
- The public SSE union is `start`, `assistant_item_start`,
  `assistant_item_delta`, `assistant_item_complete`, `activity`, `references`,
  `complete`, and `error`. Item completion is authoritative. Clients may show
  provisional text immediately and must move the same item by stable ID when
  its `progress | final` phase arrives.
- Progress and activity share one monotonically increasing sequence. An
  activity update reuses its ID and sequence. Public activity omits the raw
  tool name and exposes only category, state, bounded subject, and result
  counts.
- Terminal traces persist ordered `progress | activity` entries and citation
  counts. The final answer remains solely in `Message.content`.
- Only a final item may materialize references. Progress may contain safe,
  concise stage narration, but citation markers are removed without registering
  sources.
- The server never returns provider reasoning/ThinkingPart, chain-of-thought,
  heartbeat events, tool arguments, raw results, or tool identity. Those remain
  in controlled diagnostics and the invocation journal.
- The previous tool loop, final-answer model call, `finish_tool_use`, search
  fallback, iteration prompts, and legacy trace parser are removed without a
  compatibility layer.

## Consequences

Ordinary requests can be answered with zero tools and therefore produce only a
final item. Research and workspace requests can interleave concise progress
items with multiple tool activities before the final answer. Context-specific
entry points remain product compositions over one runtime.

The contract is deliberately destructive while Scholens is local-only: there
is no dual reducer, feature flag, legacy trace union, or compatibility parser.
Existing local JSONB traces are cleared once; message bodies and conversations
remain intact.
