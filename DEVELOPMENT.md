# Development Setup

Three services run locally: **server** (API), **client** (Next.js), and **jobs** (Celery). More detail: [server/README.md](./server/README.md), [client/README.md](./client/README.md), [jobs/README.md](./jobs/README.md).

## Prerequisites

Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node.js + Yarn, PostgreSQL, and Docker (RabbitMQ + Redis for jobs).

## Ports

| Service           | Port        | Start                            |
| ----------------- | ----------- | -------------------------------- |
| Client            | 3000        | `corepack yarn dev` in `client/` |
| Server            | 8000        | `uv run start` in `server/`      |
| Jobs API          | 8001        | `uv run start` in `jobs/`        |
| RabbitMQ / Redis  | 5672 / 6379 | Docker via `jobs` `uv run start` |
| Flower (optional) | 5555        | `jobs/./scripts/start_flower.sh` |

## Environment files

OpenPaper follows the same “one documented environment catalog” convention as
Scholight. The canonical template is [`.env.example`](./.env.example). Copy it
into each service; unused variables are ignored:

```bash
cp .env.example server/.env
cp .env.example jobs/.env
cp .env.example client/.env.local
```

**Must match across server and jobs:** `CELERY_BROKER_URL`, S3/AWS bucket vars, `JOBS_INTERNAL_SECRET` (Zotero auto-sync). Server needs `CELERY_API_URL=http://localhost:8001`; jobs needs `WEBHOOK_BASE_URL=http://localhost:8000`.

### Required for a minimal local stack

| Variable                                                                                 | Where                                                     |
| ---------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| `DATABASE_URL`                                                                           | server                                                    |
| `GEMINI_API_KEY`, `GOOGLE_API_KEY`                                                       | server, jobs                                              |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `S3_BUCKET_NAME`, `CLOUDFLARE_BUCKET_NAME` | server + jobs                                             |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`                                             | server + jobs                                             |
| `CELERY_API_URL`                                                                         | server                                                    |
| `WEBHOOK_BASE_URL`                                                                       | jobs                                                      |
| `AUTH_JWT_SECRET` (32+ bytes)                                                            | server                                                    |
| `CLIENT_DOMAIN`                                                                          | server (`http://localhost:3000`)                           |
| `NEXT_PUBLIC_API_URL`                                                                    | client                                                    |

Optional integrations (Zotero, Stripe, Discover, audio, email, PostHog, admin,
etc.) are grouped in the root `.env.example`.

**Jobs tip:** set `ZOTERO_SYNC_INTERVAL_SECONDS=60` in `jobs/.env` when testing Celery Beat locally.

### Which account database is used?

`cloud-auth` is embedded in the OpenPaper API; it is not a separate service.
Unless `AUTH_DATABASE_URL` is explicitly set, both cloud-auth and OpenPaper use
`DATABASE_URL`.

- To share local accounts with Scholight, point `DATABASE_URL` at the same local
  `sanchezcloud` database containing the `auth` schema.
- To use AWS RDS, use the dedicated least-privilege OpenPaper roles and TLS
  settings documented in
  [`deploy/production/runtime.env.example`](./deploy/production/runtime.env.example).
- OpenPaper and Scholight deliberately use different JWT secrets and
  `client_id` values even though they share `auth.users`.
- Both products may use the same Aliyun DirectMail account, while keeping their
  sender alias and action URLs product-specific.

## First-time setup

```bash
git clone git@github.com:khoj-ai/openpaper.git && cd openpaper

# Server
cp .env.example server/.env
cd server && uv sync
# Provision auth/openpaper schemas with separate owners. Apply cloud-auth from
# its own repository first, then apply only OpenPaper's migration:
uv run --env-file .env --project ../../cloud-auth cloud-auth migrate
uv run python -m app.scripts.migrate_product

# Jobs
cd ..
cp .env.example jobs/.env
cd jobs && uv sync

# Client
cd ..
cp .env.example client/.env.local
cd client && corepack yarn install
```

## Start locally (daily)

Use separate terminals, in this order:

| #   | Directory | Command                                                                                  |
| --- | --------- | ---------------------------------------------------------------------------------------- |
| 1   | `jobs/`   | `uv run start` — Docker RabbitMQ/Redis, Celery worker, Celery Beat (Zotero sync), jobs API |
| 2   | `server/` | `uv run start` — loads `.env`, applies OpenPaper migrations, starts API                  |
| 3   | `client/` | `corepack yarn dev`                                                                      |

Check: [localhost:8000/docs](http://localhost:8000/docs), [localhost:3000](http://localhost:3000), worker log shows `celery@... ready`.
