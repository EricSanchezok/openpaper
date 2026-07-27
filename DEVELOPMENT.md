# Development Setup

Three services run locally: **server** (API), **client** (Next.js), and **jobs** (Celery). More detail: [server/README.md](./server/README.md), [client/README.md](./client/README.md), [jobs/README.md](./jobs/README.md).

## Prerequisites

Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node.js 22 LTS + Yarn,
PostgreSQL, and Docker (RabbitMQ + Redis for jobs). Avoid odd-numbered Node
releases; the frontend dependency graph follows the active/LTS Node support
window enforced in `client/package.json`.

## Ports

| Service           | Port        | Start                            |
| ----------------- | ----------- | -------------------------------- |
| Client            | 3000        | `corepack yarn dev` in `client/` |
| Server            | 8000        | `uv run start` in `server/`      |
| Jobs API          | 8001        | `uv run start` in `jobs/`        |
| RabbitMQ / Redis  | 5672 / 6379 | Docker via `jobs` `uv run start` |
| Flower (optional) | 5555        | `jobs/./scripts/start_flower.sh` |

## Environment files

Scholens follows the same “one documented environment catalog” convention as
Scholight. The canonical template is [`.env.example`](./.env.example). Create
each runtime file from the relevant section of that catalog:

S3、MinerU、MOSS Voice 和 DeepSeek 的账号申请步骤见
[`docs/setup/external-services.zh-CN.md`](./docs/setup/external-services.zh-CN.md)。

```bash
touch server/.env jobs/.env client/.env.local
```

The root file is a committed catalog, not a runtime file. Each process reads
the private file in its own working directory:

| Runtime file        | Owned configuration                               |
| ------------------- | ------------------------------------------------- |
| `server/.env`       | Database, cloud-auth, MOSS, API integrations      |
| `jobs/.env`         | MinerU, background processing, webhook delivery   |
| Both Python files   | S3, DeepSeek, broker URLs, webhook signing secret |
| `client/.env.local` | `NEXT_PUBLIC_*` browser configuration only        |

Do not copy Python-service credentials into `client/.env.local`. Next.js only
exposes `NEXT_PUBLIC_*` values to browser code, but keeping secrets out of the
client build context is the safer operational boundary.

**Must match across server and jobs:** `CELERY_BROKER_URL`, S3/AWS bucket vars,
`DEEPSEEK_*`, and `JOBS_WEBHOOK_SIGNING_SECRET`. Server needs
`CELERY_API_URL=http://localhost:8001`; jobs needs
`WEBHOOK_BASE_URL=http://localhost:8000`.

### Required for a minimal local stack

| Variable                                                                                 | Where                                                     |
| ---------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| `DATABASE_URL`                                                                           | server                                                    |
| `DEEPSEEK_API_KEY`                                                                       | server, jobs                                              |
| `MINERU_API_TOKEN`                                                                       | jobs                                                      |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `S3_BUCKET_NAME`, `CLOUDFLARE_BUCKET_NAME` | server + jobs                                             |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`                                             | server + jobs                                             |
| `CELERY_API_URL`                                                                         | server                                                    |
| `WEBHOOK_BASE_URL`                                                                       | jobs                                                      |
| `AUTH_JWT_SECRET` (32+ bytes)                                                            | server                                                    |
| `CLIENT_DOMAIN`                                                                          | server (`http://localhost:3000`)                           |
| `NEXT_PUBLIC_API_URL`                                                                    | client                                                    |

MOSS Voice is required only for audio overviews. Zotero, Stripe, email, PostHog,
and admin variables are grouped in the root `.env.example`.

Scholens discovers remote model tools through MCP:

- `ANYSEARCH_MCP_URL` and optional `ANYSEARCH_API_KEY` provide general search
  and page extraction. Anonymous access works locally with lower quotas.
- `SCHOLIGHT_MCP_URL` provides ranked paper search.
  `SCHOLIGHT_MCP_DELEGATION_JWT_SECRET` signs a fresh 60-second delegation for the
  current user so Scholight charges that user's own search quota.

**Jobs tip:** set `ZOTERO_SYNC_INTERVAL_SECONDS=60` in `jobs/.env` when testing Celery Beat locally.

### Which account database is used?

`cloud-auth` is embedded in the Scholens API; it is not a separate service.
Unless `AUTH_DATABASE_URL` is explicitly set, both cloud-auth and Scholens use
`DATABASE_URL`.

- To share local accounts with Scholight, point `DATABASE_URL` at the same local
  `sanchezcloud` database containing the `auth` schema.
- To use AWS RDS, use the dedicated least-privilege Scholens roles and TLS
  settings documented in
  [`deploy/production/runtime.env.example`](./deploy/production/runtime.env.example).
- Scholens and Scholight deliberately use different JWT secrets and
  `client_id` values even though they share `auth.users`.
- Both products may use the same Aliyun DirectMail account, while keeping their
  sender alias and action URLs product-specific.

## First-time setup

```bash
git clone <your-scholens-fork-url> scholens && cd scholens

# Server
touch server/.env
cd server && uv sync
# Provision auth/scholens schemas with separate owners. Apply cloud-auth from
# its own repository first, then apply only Scholens's migration:
uv run --env-file .env --project ../../cloud-auth cloud-auth migrate
psql postgresql://postgres:postgres@127.0.0.1:5432/sanchezcloud \
  -c 'CREATE SCHEMA IF NOT EXISTS scholens AUTHORIZATION openpaper_local'
uv run python -m app.scripts.migrate_product

# Jobs
cd ..
touch jobs/.env
cd jobs && uv sync

# Client
cd ..
touch client/.env.local
cd client && corepack yarn install
```

`openpaper_local` is the local product migration role. If `DATABASE_URL` uses
a different role, substitute it in this one-time administrator command.
Alembic intentionally refuses to migrate a `scholens` schema owned by another
role.

## Start locally (daily)

Use separate terminals, in this order:

| #   | Directory | Command                                                                                  |
| --- | --------- | ---------------------------------------------------------------------------------------- |
| 1   | `jobs/`   | `uv run start` — Docker RabbitMQ/Redis, Celery worker, Celery Beat (Zotero sync), jobs API |
| 2   | `server/` | `uv run start` — loads `.env`, applies Scholens migrations, starts API                  |
| 3   | `client/` | `corepack yarn dev`                                                                      |

Check: [localhost:8000/docs](http://localhost:8000/docs), [localhost:3000](http://localhost:3000), worker log shows `celery@... ready`.

## Reset only the local product schema

Scholens owns `scholens`; cloud-auth independently owns `auth`. During this
pre-release phase you may reset local product data, but never drop `auth`:

```sql
DROP SCHEMA IF EXISTS scholens CASCADE;
CREATE SCHEMA scholens AUTHORIZATION scholens_migrator;
```

Run those statements with a local database administrator, substitute the
actual local product migration role, then rebuild and verify the schema:

```bash
cd server
uv run alembic upgrade head
uv run alembic upgrade head  # intentional no-op/idempotency check
uv run alembic check         # must report no new upgrade operations
```

The migration role must own `scholens` and have read/write access required by
product foreign keys, but it must not own or have `CREATE` on `auth`.
