# Backend capability architecture

Scholens exposes one set of business capabilities through several adapters.
The public HTTP API, the in-process Agent tools, internal job callbacks, and a
future MCP server are entry points; none of them owns paper, project, billing,
or Zotero business rules.

```text
HTTP / Agent / future MCP / job callback
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
- `transport` validates and translates protocols only. It resolves use cases
  through `server/app/bootstrap/container.py`; it does not select adapters or
  duplicate business rules.
- Cross-module work is coordinated through application ports/facades and
  wired in the composition root. ORM relationship imports used only under
  `TYPE_CHECKING` are mapping metadata, not business dependencies.

The request-scoped unit of work commits once after a successful response and
rolls back on failure. Provider ledgers, the durable outbox dispatcher, and
garbage collection own independent background transactions because they must
record progress across external calls.

## Replaceable search

`PaperSearchPort` is the stable application boundary. The current
`postgres_fts` adapter ranks accessible document metadata and passages using
PostgreSQL full-text search. `PAPER_SEARCH_BACKEND` is validated at startup.
A future embedding or hybrid implementation is added as another adapter and
selected only in the composition root; HTTP, Agent, and MCP contracts do not
change.

## Adding a capability or adapter

1. Define transport-neutral request/response contracts and a port in the
   owning module's `application` package.
2. Implement the use case once and test its policy, authorization, and
   idempotency behavior without HTTP.
3. Add or replace infrastructure adapters and wire them in
   `bootstrap/container.py`.
4. Keep every protocol adapter thin and delegate to the same use case.
5. Update the OpenAPI snapshot and add an end-to-end contract test when the
   public surface changes.

This boundary also applies when identity, Zotero, billing, or a future product
area is reorganized; `/api/v1` is a platform version, not a paper-only
namespace.
