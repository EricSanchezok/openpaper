# Server

This server manages the backend for the Scholens project, which allows users to upload, chat with, annotate, and manage research papers in one place.

Shared identity integration follows the
[`sanchezcloud-identity` engineering handbook](https://github.com/EricSanchezok/sanchezcloud-identity/blob/main/docs/README.md).
Scholens-specific ownership is documented in
[`docs/architecture/data-ownership.md`](../docs/architecture/data-ownership.md).

## Prerequisites

- Python 3.12 or higher
- [Uv](https://docs.astral.sh/uv/getting-started/installation/)
- [PostgreSQL database](http://postgresql.org/download/) (Make sure it's running with a user postgres)
- [Docker](https://docs.docker.com/get-docker/) (for RabbitMQ/Redis used by PDF processing and Redis-backed AI capacity limits)
- Jobs service running for uploads and Zotero import (see [jobs/README.md](../jobs/README.md))

## Setup

1. Install dependencies

```bash
uv sync
source .venv/bin/activate
```

2. Get an API key from [Google AI Studio](https://aistudio.google.com/apikey)

3. Set up environment variables from the repository-level catalog. Copy only
   the Server section; the root file is not itself a runtime file.

```bash
touch .env
```

At minimum, point `DATABASE_URL` at a `sanchezcloud` database with migrated
`auth` and `scholens` schemas, then replace the placeholder provider keys for
the features you want to exercise. See [`../DEVELOPMENT.md`](../DEVELOPMENT.md)
for the shared-local-account and AWS RDS distinction.

The backend exposes one versioned capability surface and shares its application
use cases with Agent adapters and the authenticated `/mcp` server. Architecture rules,
resource semantics, transaction ownership, and the replaceable search boundary
are documented in
[`../docs/architecture/backend-capabilities.md`](../docs/architecture/backend-capabilities.md).

Scholight is an automatically authenticated built-in connector. AnySearch,
Tavily, Exa, and Firecrawl are optional user-level connectors. Their native MCP
tool schemas are discovered dynamically; the runtime does not maintain a
second capability map or provider-specific tool wrappers.

## Start the Application

1. Start the jobs service (RabbitMQ + Celery worker) in a separate terminal:

```bash
cd ../jobs
uv run --frozen --no-sync start
```

2. Start the API server:

```bash
uv run --frozen --no-sync start
```

The command binds to `127.0.0.1:7301`, rejects any `DATABASE_URL` other than
the shared local PostgreSQL at `127.0.0.1:55432/sanchezcloud`, and does not run
migrations. Apply product migrations explicitly with the `scholens_migrator`
role as documented in [`../DEVELOPMENT.md`](../DEVELOPMENT.md).

The local broker is `pyamqp://guest@127.0.0.1:55672//` when the Jobs profile is
enabled.

The ordinary Scholens local environment uses an isolated remote dev S3 bucket
and Aliyun DirectMail for real verification and password-reset messages. It
does not require Mailpit or MinIO. Keep both providers' credentials in the
ignored `server/.env`; Jobs receives the same dev S3 settings through its own
ignored `jobs/.env`. Production RDS, S3, and mail resources must never be used
by local startup.

## API Documentation

FastAPI automatically generates API documentation. Once the application is running, you can access:

- Swagger UI: `http://127.0.0.1:7301/docs`
- ReDoc: `http://127.0.0.1:7301/redoc`

Public application routes are under `/api/v1`; provider webhooks are under
`/webhooks/v1`. `/internal/v1` is reserved for authenticated worker traffic and
is intentionally not routed by the production edge proxy.

Conversation turns are created at
`POST /api/v1/conversations/{conversation_id}/turns`; retrying the latest turn
creates another response variant at
`POST /api/v1/conversations/{conversation_id}/turns/{turn_id}/responses`.
Both generation endpoints stream standard Server-Sent Events. Consumers must handle
the typed `start`, `assistant_item_start`, `assistant_item_delta`,
`assistant_item_complete`, `activity`, `references`, `complete`, and `error`
events and treat `complete` or `error` as terminal. Assistant items begin as
provisional and are authoritatively classified on completion as `progress` or
`final`; clients move the same stable item instead of duplicating its text.
Progress and activity entries share a monotonic sequence. Requests include the
UI locale and a validated IANA time zone. `activity` contains only a sanitized
category/state/subject projection and intentionally omits the raw tool name.
Model reasoning, provider heartbeats, tool arguments, and tool payloads are
never part of the public stream. References may be emitted only for the final
assistant item. The runtime passes these same typed event models to the HTTP
adapter rather than maintaining a second dictionary-shaped protocol. Completed
assistant items must contain visible text; user-visible progress is bounded to
4,000 characters, and a response without a visible final answer is failed
instead of persisting an empty response variant. A turn owns the immutable user
prompt and one or more generated responses; only the latest turn may be retried
or switch its selected response. Creating the next turn prunes unselected
variants from the prior turn, so completed history has one canonical response.
There is no private delimiter. Clients may abort the request, but must not
automatically retry this non-idempotent operation.

# Migrations

This project uses Alembic for database migrations. Commands are run through the
locked `uv` environment:

```bash
uv run alembic revision --autogenerate -m "migration message"
```

To apply the migration, run:

```bash
uv run alembic upgrade head
```

To downgrade the migration, run:

```bash
uv run alembic downgrade -1
```

Before committing a migration, run `uv run alembic check`. Alembic compares
only the `scholens` schema; `auth` belongs to sanchezcloud-identity and other product
schemas are deliberately outside this migration environment. The local
product-only reset procedure is documented in
[`DEVELOPMENT.md`](../DEVELOPMENT.md#reset-only-the-local-product-schema).

# Tests

Run the complete Server quality gate from the `server` directory:

```bash
uv run ruff check app tests migrations
uv run mypy app
uv run pytest -q
```

## Chat with Knowledge Base

We have an `Ask` page, which allows you to ask questions across your entire knowledge base. AI-generated responses come with inline citations which will link to the original papers and show the text citation. Deep-linking is not yet available, but is planned.

The response agent is one contextual Pydantic AI runtime with access to the
authorized subset of the canonical workspace and connector tools:

- `search_papers`
- `get_paper_abstract`
- `search_paper_content`
- `get_paper_content_range`
- `get_paper_content`
- workspace management tools selected from the same catalog exposed by `/mcp`

![knowledge base research diagram](./lr_research_diagram.png)

Unified Conversation agent workflow:

```
+----------------+      +-------------------------------------------------+    +-------------------+
|      User      |----->|             FastAPI Server                    |----->|        LLM        |
+----------------+      |         (conversation_agent.py)               |      +-------------------+
        ^             |                                                 |              ^
        |             |  1. Run one model loop                           |              |
        |             |     - answer directly when tools are unnecessary |              |
        |             |     - call 0..n authorized tools                 |--------------+
        |             |  2. Dispatch every call through Scholens         |
        |             |     - validate arguments and permissions         |
        |             |     - journal writes and enforce idempotency      |
        |             |     - project safe, bounded results               |
        |             |  3. Register validated sources incrementally      |
        |             |  4. Stream answer and materialize citations       |--------------+
        |             |     - expose sanitized activity only              |              |
        |             |     - persist typed terminal trace                 |              |
        |             +-------------------------------------------------+              |
        |                           |                                                  |
        +---------------------------+--------------------------------------------------+
                              (Streamed response with citations)
```
