# ADR 0008: One Pydantic AI conversation agent with Scholens-owned tools

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
- The public SSE union is `start`, `activity`, `content_delta`, `references`,
  `complete`, and `error`. Activity records are typed and sanitized. The server
  never returns chain-of-thought or raw tool payloads.
- Terminal traces persist only final activity records and citation counts.
- The previous tool loop, final-answer model call, `finish_tool_use`, search
  fallback, iteration prompts, and legacy trace parser are removed without a
  compatibility layer.

## Consequences

Ordinary requests can be answered with zero tools, while research and
workspace requests can call multiple tools and continue naturally after a
recoverable tool failure. Context-specific entry points remain product
compositions over one runtime. The destructive contract change requires the
Web client, generated types, fixtures, Storybook states, and local persisted
traces to move in the same development cut.
