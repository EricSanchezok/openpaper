# Backend capability architecture

Scholens exposes one set of business capabilities through several adapters.
The public HTTP API, the in-process Agent tools, internal job callbacks, and the
inbound MCP server are entry points; none of them owns paper, project, billing,
or Zotero business rules.

```text
HTTP / Agent / MCP / job callback
                 |
                 v
 authentication + Actor
 permission/tool preflight
 OperationContext provenance
                 |
                 v
          ApplicationExecutor
                 |
                 v
        module application use case
                 |
          domain policy + ports
                 |
                 v
 infrastructure adapters (PostgreSQL, S3, Stripe, Zotero, jobs, LLM)
```

## Stable contracts

The browser-facing API is mounted once at `/api/v1`. Provider callbacks are
under `/webhooks/v1`, and worker-only operations are under `/internal/v1`.
Production routing deliberately does not expose `/internal/v1`.

Public resources use canonical identifiers:

- `document_id` identifies a paper everywhere. Association-row identifiers
  are named explicitly and are never presented as paper identifiers.
- Collections return `{ "items": [...], "next_cursor": "..." }`; cursors are
  opaque, signed, query-bound tokens.
- Resource creation returns `201`, accepted asynchronous work returns `202`,
  and deletions without a response body return `204`.
- Paper ingestion, Zotero imports, and generated artifacts accept
  `Idempotency-Key`. Reusing a key with a different request returns `409`.

The reviewed public surface is stored in
`server/openapi/v1-contract.json`. A contract test fails whenever a route is
added, removed, renamed, or changes method without an intentional snapshot
update.

## Module rules

Each business module owns `domain`, `application`, and `infrastructure`
packages.

- `domain` contains pure rules and cannot import web frameworks, persistence,
  SDKs, or another module's infrastructure.
- `application` owns complete use cases and transaction intent. It depends on
  protocols and public application contracts, never concrete adapters.
- `infrastructure` implements ports. Repository methods flush but do not
  commit a caller-owned request transaction.
- `transport` validates and translates protocols only. HTTP, Agent, job, and
  MCP adapters receive the same `ApplicationExecutor`; they never
  receive a SQLAlchemy `Session`, select adapters, or duplicate business
  rules.
- `bootstrap/capabilities.py` is the canonical session-bound application
  surface. `bootstrap/container.py` is the only composition root that selects
  concrete adapters.
- Cross-module work is coordinated through application ports/facades and
  wired in the composition root. ORM relationship imports used only under
  `TYPE_CHECKING` are mapping metadata, not business dependencies.

`ApplicationExecutor.query` closes without committing.
`ApplicationExecutor.command` and `command_async` commit exactly once after a
successful operation and roll back on failure. Nested executor operations are
rejected.

External I/O must not run inside an open database transaction. Workflows use:

```text
command: prepare/reserve
        -> commit
external call or stream
        ->
command: complete
failure -> command: fail/release
```

Chat streaming, paper ingestion, Research generation, onboarding, Stripe, and
Zotero import/sync follow this shape. Agent and MCP paper tools obtain a fresh
short operation for every tool call rather than retaining a session for the
life of a conversation.

## Authentication, permission, and operation provenance

Authentication, authorization, and attribution are deliberately separate:

- sanchezcloud-identity sessions authenticate browser users; Scholens AccessKeys
  authenticate MCP clients;
- `WorkspacePermission` and `ToolAccess` determine which catalog tools are
  visible and executable;
- `Actor` plus Domain policy authorizes the concrete resource;
- immutable `OperationContext` records only trace, direct initiator, typed
  origin, and a non-sensitive credential reference.

Changing an Operation origin or credential must never change a Domain
authorization result. Raw credential, signature, OAuth callback, and webhook
verification complete before an `OperationContext` is constructed.

Every product-changing Application command receives an explicit
`operation: OperationContext`. Its private, session-bound `OperationJournal`
appends stable business actions in the same UnitOfWork as the business write.
Queries, rejected operations, no-ops, technical leases, and replayed tool
invocations do not create Journal entries. The Journal is append-only and has
no public read capability or transport endpoint.

Conversation user messages are USER root operations. Model tool calls,
answers, citations, and generated titles are AGENT child operations that retain
the turn correlation. Jobs persist only their origin operation and correlation
UUIDs, then callbacks resume a new SYSTEM operation after signature and owner
verification.

A Conversation title is generated once, after its first successful assistant
reply. Later turns never invoke the title model or rewrite the Sidebar title;
an explicit user title always wins over a concurrent generated title.

## Canonical tool catalog

Every model-visible research workspace tool is defined once in
`server/app/tooling/workspace.py`. A `ToolDefinition` owns its stable name,
description, Pydantic input model, execution kind, and application handler.
Independent Conversation and MCP profiles select definitions from the same
catalog; transports never copy schemas or handlers.

## Single conversation agent

Home, project, and paper conversations all execute through one
`ScholensConversationAgent`. The conversation scope supplies initial context and
the default paper collection; it does not select a different runtime or tool
set. Pydantic AI owns only the model/tool loop and model event decoding.
Scholens retains ownership of authentication, tool visibility, resource
authorization, operation provenance, argument validation, idempotent dispatch,
source registration, citation validation, persistence, limits, and
cancellation.

The model receives an injected absolute time for the request's validated IANA
time zone, so current-date answers do not rely on model memory. Tool results are
bounded and projected before returning to the model. `Agent.iter()` exposes
complete model and tool nodes to the harness: text from a response that calls a
tool completes as a `progress` item, while the accepted no-tool response
completes as the `final` item. Both use stable IDs and share a monotonic sequence
with sanitized activity records. The persisted trace contains ordered progress
and activity entries; final answer text remains in the Message row.

The public Conversation stream exposes item lifecycle events, sanitized
activity, final-only server-generated references, and one terminal event. Raw
reasoning, provider heartbeats, tool identity, full parameters, and tool return
payloads remain internal diagnostics.

`ToolDispatcher` validates arguments and executes each tool through a fresh
`ApplicationExecutor` operation. Query tools never commit. Command tools commit
their business change and completed invocation ledger row atomically. Workflow
tools use an explicit external-I/O workflow and then persist the completed
result. Conversation write invocation identities include conversation, turn,
tool-call arguments, and tool name; MCP identities use the authenticated token
session and JSON-RPC request identity. Replays return the persisted result, and
conflicting argument reuse returns `tool_invocation_conflict`.

The inbound Streamable HTTP MCP endpoint is `/mcp`, outside the public OpenAPI
surface. Every request requires a Scholens AccessKey in the Bearer header.
The key's immutable permission snapshot determines the MCP `ToolAccess`; its
resolved Actor still passes through the same resource authorization as HTTP
and Conversation calls. MCP defaults paper operations to the authenticated
user's complete accessible paper collection. Protocol code only authenticates,
builds typed provenance, selects a profile, and delegates to
`ToolDispatcher`.

Only progress-owning infrastructure may commit independently. The executable
architecture whitelist contains narrow technical ledgers and dispatchers such
as the Stripe webhook ledger and durable Jobs outbox. They reserve progress in
a short transaction, perform external I/O with no Session, and finalize in
another short transaction. Product workflows, including Zotero, citation
recovery, discovery, document postprocessing, and billing, use
`ApplicationExecutor` stages; repositories themselves never commit.

Domain concepts have one canonical type name. Compatibility assignments such
as `OldAccess = NewAccessDecision` are forbidden by an architecture test; a
distinct projection type is allowed only when it carries genuinely different
data or responsibility.

## Replaceable search

`PaperSearchPort` is the stable application boundary. The current
`postgres_fts` adapter ranks accessible document metadata and passages using
PostgreSQL full-text search. `PAPER_SEARCH_BACKEND` is validated at startup.
A future embedding or hybrid implementation is added as another adapter and
selected only in the composition root; HTTP, Agent, and MCP contracts do not
change.

The search collection named `library` is a computed access view, not a synonym
for `LibraryPaper` membership. It contains the user's personal-library papers
plus papers available through Projects they own or collaborate on. Access is
re-evaluated for each operation, and the outer `Document` query keeps papers
that are reachable through several paths unique. Personal-library listing,
tags, storage accounting, and ingestion ownership continue to use
`LibraryPaper`; no Project paper is copied into the personal library.

## Adding a capability or adapter

1. Define transport-neutral request/response contracts and a port in the
   owning module's `application` package.
2. Implement the use case once and test its policy, authorization, and
   idempotency behavior without HTTP.
3. Add or replace infrastructure adapters and wire them in
   `bootstrap/container.py`.
4. Expose the use case on `ApplicationCapabilities`; use a workflow only when
   external I/O requires explicit prepare/complete phases.
5. Give every real command a stable owning-module `OperationAction`, accept an
   explicit `OperationContext`, and append through its private Journal only
   when the gateway reports a true change.
6. For a model-visible capability, add one `ToolDefinition` and select it in
   the appropriate profiles. MCP code must not call repositories or HTTP
   routes.
7. Update the OpenAPI snapshot and add an end-to-end contract test when the
   public surface changes.

This boundary also applies when identity, Zotero, billing, or a future product
area is reorganized; `/api/v1` is a platform version, not a paper-only
namespace.
