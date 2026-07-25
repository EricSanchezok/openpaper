# Server

This server manages the backend for the Scholens project, which allows users to upload, chat with, annotate, and manage research papers in one place.

## Prerequisites
- Python 3.12 or higher
- [Uv](https://docs.astral.sh/uv/getting-started/installation/)
- [PostgreSQL database](http://postgresql.org/download/) (Make sure it's running with a user postgres)
- [Docker](https://docs.docker.com/get-docker/) (for RabbitMQ/Redis used by PDF processing)
- Jobs service running for uploads and Zotero import (see [jobs/README.md](../jobs/README.md))

## Setup

1. Install dependencies
```bash
uv sync
source .venv/bin/activate
```

2. Get an API key from [Google AI Studio](https://aistudio.google.com/apikey)

3. Set up environment variables from the repository-level catalog
```bash
cp ../.env.example .env
```

At minimum, point `DATABASE_URL` at a `sanchezcloud` database with migrated
`auth` and `scholens` schemas, then replace the placeholder provider keys for
the features you want to exercise. See [`../DEVELOPMENT.md`](../DEVELOPMENT.md)
for the shared-local-account and AWS RDS distinction.

AnySearch and Scholight are connected as remote Streamable HTTP MCP servers.
Their tool schemas are discovered at runtime, so citation recovery uses the
providers' native `search`, `extract`, and `search_papers` tools rather than
maintaining local Exa/Firecrawl wrappers.

## Start the Application

1. Start the jobs service (RabbitMQ + Celery worker) in a separate terminal:
```bash
cd ../jobs
uv run start
```

2. Start the API server:
```bash
uv run start
```

Optional: set `CELERY_BROKER_URL=pyamqp://guest@localhost:5672//` in `.env` if you use a non-default broker.

## API Documentation

FastAPI automatically generates API documentation. Once the application is running, you can access:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

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
only the `scholens` schema; `auth` belongs to cloud-auth and other product
schemas are deliberately outside this migration environment. The local
product-only reset procedure is documented in
[`DEVELOPMENT.md`](../DEVELOPMENT.md#reset-only-the-local-product-schema).

# Tests

Tests live in the `tests/` folder and use Python's built-in `unittest`. Run them from the `server` directory:

```bash
# All tests
uv run python -m unittest discover -s tests

# A single test file
uv run python -m unittest tests.test_zotero_sync

# A single test case or method
uv run python -m unittest tests.test_zotero_sync.TestZoteroAnnotationPayload
uv run python -m unittest tests.test_zotero_sync.TestZoteroAnnotationPayload.test_serialize_annotations_payload_keeps_keys
```

## Chat with Knowledge Base

We have an `Ask` page, which allows you to ask questions across your entire knowledge base. AI-generated responses come with inline citations which will link to the original papers and show the text citation. Deep-linking is not yet available, but is planned.

The response agent works by sending off an agent with access to a series of research tools:
- `read_file`
- `search_file`
- `view_file`
- `read_abstract`
- `search_all_files`

![knowledge base research diagram](./lr_research_diagram.png)

Multi-paper chat workflow:

```
+----------------+      +-------------------------------------------------+    +-------------------+
|      User      |----->|             FastAPI Server                    |----->|        LLM        |
+----------------+      |       (multi_paper_operations.py)             |      +-------------------+
        ^             |                                                 |              ^
        |             |  1. gather_evidence(question)                   |              |
        |             |     - Iteratively calls LLM with tools:         |              |
        |             |       - search_all_files(query)                 |--------------+
        |             |       - read_file(paper_id, query)              |
        |             |       - ...                                     |
        |             |     - Compacts evidence if it gets too large    |
        |             |                                                 |
        |             |  2. chat_with_papers(question, evidence)        |
        |             |     - Sends evidence and question to LLM        |--------------+
        |             |     - Streams response back to user             |              |
        |             |     - Parses citations from response            |              |
        |             +-------------------------------------------------+              |
        |                           |                                                  |
        +---------------------------+--------------------------------------------------+
                              (Streamed response with citations)
```
