# Development Setup

Four application services can run locally: **server** (API), the new **web** foundation,
the legacy **client** used only for comparison, and **jobs** (Celery). Storybook runs
independently for isolated component development. More detail:
[server/README.md](./server/README.md), [web/README.md](./web/README.md),
[client/README.md](./client/README.md), [jobs/README.md](./jobs/README.md).

## Prerequisites

Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node.js 22 LTS, pnpm + Yarn,
PostgreSQL, and Docker (RabbitMQ + Redis for jobs). Avoid odd-numbered Node
releases; the frontend dependency graph follows the active/LTS Node support
window enforced in `client/package.json`.

## Ports

| Service           | Port        | Start                            |
| ----------------- | ----------- | -------------------------------- |
| Web (canonical)   | 3000        | `pnpm dev` in `web/`             |
| Legacy client     | 3001        | `corepack yarn dev` in `client/` |
| Storybook         | 6006        | `pnpm storybook` in `web/`       |
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
touch server/.env jobs/.env web/.env.local client/.env.local
```

The root file is a committed catalog, not a runtime file. Each process reads
the private file in its own working directory:

| Runtime file        | Owned configuration                                     |
| ------------------- | ------------------------------------------------------- |
| `server/.env`       | Database, sanchezcloud-identity, MOSS, API integrations |
| `jobs/.env`         | MinerU, background processing, webhook delivery         |
| Both Python files   | S3, DeepSeek, broker URLs, webhook signing secret       |
| `web/.env.local`    | canonical `NEXT_PUBLIC_*` browser configuration         |
| `client/.env.local` | legacy comparison client configuration                  |

Do not copy Python-service credentials into `client/.env.local`. Next.js only
exposes `NEXT_PUBLIC_*` values to browser code, but keeping secrets out of the
client build context is the safer operational boundary.

**Must match across server and jobs:** `CELERY_BROKER_URL`, S3/AWS bucket vars,
`DEEPSEEK_*`, and `JOBS_WEBHOOK_SIGNING_SECRET`. Server needs
`CELERY_API_URL=http://localhost:8001`; jobs needs
`WEBHOOK_BASE_URL=http://localhost:8000`.

### Required for a minimal local stack

| Variable                                                                                 | Where                                                  |
| ---------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| `DATABASE_URL`                                                                           | server                                                 |
| `DEEPSEEK_API_KEY`                                                                       | server, jobs                                           |
| `MINERU_API_TOKEN`                                                                       | jobs                                                   |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `S3_BUCKET_NAME`, `CLOUDFLARE_BUCKET_NAME` | server + jobs                                          |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`                                             | server + jobs                                          |
| `CELERY_API_URL`                                                                         | server                                                 |
| `WEBHOOK_BASE_URL`                                                                       | jobs                                                   |
| `AUTH_JWT_SECRET` (32+ bytes)                                                            | server                                                 |
| `CLIENT_DOMAIN`                                                                          | server canonical URL (`http://localhost:3000`)         |
| `CLIENT_ALLOWED_ORIGINS`                                                                 | server (`http://localhost:3000,http://localhost:3001`) |
| `NEXT_PUBLIC_API_URL`                                                                    | web + legacy client                                    |

MOSS Voice is required only for audio overviews. Zotero, Stripe, email, PostHog,
and admin variables are grouped in the root `.env.example`.

Scholens discovers remote model tools through MCP. Scholight is the built-in
provider: `SCHOLIGHT_MCP_URL` selects its fixed endpoint and
`SCHOLIGHT_MCP_DELEGATION_JWT_SECRET` signs a fresh 60-second delegation for the
current user. AnySearch, Tavily, Exa, and Firecrawl are connected per user in
Settings; their encrypted API keys use `CONNECTOR_CREDENTIAL_ENCRYPTION_KEY`.

**Jobs tip:** set `ZOTERO_SYNC_INTERVAL_SECONDS=60` in `jobs/.env` when testing Celery Beat locally.

### Which account database is used?

`sanchezcloud-identity` is embedded in the Scholens API; it is not a separate service.
Unless `AUTH_DATABASE_URL` is explicitly set, both sanchezcloud-identity and Scholens use
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
# Provision auth/scholens schemas with separate owners. Apply sanchezcloud-identity from
# its own repository first, then apply only Scholens's migration:
uv run --env-file .env --project ../../sanchezcloud-identity sanchezcloud-identity migrate
psql postgresql://postgres:postgres@127.0.0.1:5432/sanchezcloud \
  -c 'CREATE SCHEMA IF NOT EXISTS scholens AUTHORIZATION scholens_migrator'
uv run python -m app.scripts.migrate_product

# Jobs
cd ..
touch jobs/.env
cd jobs && uv sync

# Client
cd ..
touch client/.env.local
cd client && corepack yarn install

# New web foundation
cd ..
touch web/.env.local
cd web && corepack enable && pnpm install --frozen-lockfile
```

`scholens_migrator` is the local product migration role. If `DATABASE_URL` uses
a different role, substitute it in this one-time administrator command.
Alembic intentionally refuses to migrate a `scholens` schema owned by another
role.

## Start locally (daily)

Use separate terminals, in this order:

| #   | Directory | Command                                                                                    |
| --- | --------- | ------------------------------------------------------------------------------------------ |
| 1   | `jobs/`   | `uv run start` — Docker RabbitMQ/Redis, Celery worker, Celery Beat (Zotero sync), jobs API |
| 2   | `server/` | `uv run start` — loads `.env`, applies Scholens migrations, starts API                     |
| 3   | `web/`    | `pnpm dev` — canonical web foundation on port 3000                                         |
| 4   | `client/` | `corepack yarn dev` — legacy comparison UI on port 3001                                    |

Check: [localhost:8000/docs](http://localhost:8000/docs),
[localhost:3000](http://localhost:3000), [localhost:3001](http://localhost:3001),
and confirm the worker log shows `celery@... ready`. Storybook is optional at
[localhost:6006](http://localhost:6006).

Before adding replacement-frontend product code, read the
[`web/docs` engineering handbook](./web/docs/README.md). It defines dependency
direction, feature slices, component intake, Figma/token synchronization, API
generation, testing responsibilities, and the required new-feature checklist.

## Reset only the local product schema

Scholens owns `scholens`; sanchezcloud-identity independently owns `auth`. During this
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
