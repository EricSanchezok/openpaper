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

## Local development contract

Scholens owns the `7300-7399` host-port block. Local services bind only to
`127.0.0.1`, use the fixed ports below, and fail when a port is occupied. Do not
add automatic port fallback or borrow a port from Account Center (`7100-7199`)
or Scholight (`7200-7299`). Container-internal production ports are not part of
this host-port contract.

| Service           | Host port | Start                            |
| ----------------- | --------- | -------------------------------- |
| Web (canonical)   | 7300      | `pnpm dev` in `web/`             |
| Server API        | 7301      | `uv run --frozen --no-sync start` in `server/` |
| Jobs API          | 7302      | `uv run --frozen --no-sync start` in `jobs/`   |
| Legacy client     | 7303      | `corepack yarn dev` in `client/` |
| Storybook         | 7306      | `pnpm storybook` in `web/`       |
| Flower (optional) | 7307      | `./scripts/start_flower.sh`      |

Shared local infrastructure uses ports outside all product blocks:

| Infrastructure | Host endpoint              | Container port |
| -------------- | -------------------------- | -------------- |
| PostgreSQL     | `127.0.0.1:55432`          | 5432           |
| RabbitMQ       | `amqp://127.0.0.1:55672`   | 5672           |
| Redis          | `redis://127.0.0.1:56379`  | 6379           |

Ports `59000/59001` are reserved for projects that explicitly choose local
MinIO. Scholens does not start or consume MinIO in its default local workflow;
it uses an isolated remote dev S3 bucket instead. This project-specific choice
does not require Scholight or Account Center to use the same provider.

The PostgreSQL database is shared with Account Center and Scholight, but schema
ownership is not: sanchezcloud-identity migrates only `auth.*`; Scholens migrates
only `scholens.*`. Local product startup must never connect to RDS, and no daily
startup command may install dependencies or apply migrations.

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
`CELERY_API_URL=http://127.0.0.1:7302`; jobs needs
`WEBHOOK_BASE_URL=http://127.0.0.1:7301`.

### Required for a minimal local stack

| Variable                                                                                 | Where                                                  |
| ---------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| `DATABASE_URL`                                                                           | server                                                 |
| `DEEPSEEK_API_KEY`                                                                       | server, jobs                                           |
| `MINERU_API_TOKEN`                                                                       | jobs                                                   |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `S3_BUCKET_NAME`, `CLOUDFLARE_BUCKET_NAME` | server + jobs; isolated remote dev S3                  |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`                                             | server + jobs                                          |
| `CELERY_API_URL`                                                                         | server                                                 |
| `WEBHOOK_BASE_URL`                                                                       | jobs                                                   |
| `AUTH_JWT_SECRET` (32+ bytes)                                                            | server                                                 |
| `AUTH_ALIYUN_DM_ACCESS_KEY_ID`, `AUTH_ALIYUN_DM_ACCESS_KEY_SECRET`, `AUTH_ALIYUN_DM_ACCOUNT_NAME` | server; verification/reset mail                       |
| `CLIENT_DOMAIN`                                                                          | server canonical URL (`http://127.0.0.1:7300`)         |
| `CLIENT_ALLOWED_ORIGINS`                                                                 | server (`http://127.0.0.1:7300,http://127.0.0.1:7303`) |
| `NEXT_PUBLIC_API_URL`                                                                    | web + legacy client                                    |

MOSS Voice is required only for audio overviews. Zotero, Stripe, email, PostHog,
and admin variables are grouped in the root `.env.example`.

Scholens discovers remote model tools through MCP. Scholight is the built-in
provider: `SCHOLIGHT_MCP_URL` selects its fixed endpoint and
`SCHOLIGHT_MCP_DELEGATION_JWT_SECRET` signs a fresh 60-second delegation for the
current user. AnySearch, Tavily, Exa, and Firecrawl are connected per user in
Settings; their encrypted API keys use `CONNECTOR_CREDENTIAL_ENCRYPTION_KEY`.

**Jobs tip:** set `ZOTERO_SYNC_INTERVAL_SECONDS=60` in `jobs/.env` when testing Celery Beat locally.

### Local and remote dependency policy

`sanchezcloud-identity` is embedded in the Scholens API; it is not a separate service.
Unless `AUTH_DATABASE_URL` is explicitly set, both sanchezcloud-identity and Scholens use
`DATABASE_URL`.

- Local development always uses the shared `sanchezcloud` database at
  `127.0.0.1:55432`. The Server start command rejects every other database endpoint,
  including RDS and the ordinary local port `5432`.
- RDS settings belong only in deployment-managed production environments; see
  [`deploy/production/runtime.env.example`](./deploy/production/runtime.env.example).
- Scholens and Scholight deliberately use different JWT secrets and
  `client_id` values even though they share `auth.users`.
- Products may use the same Aliyun DirectMail account, while keeping sender
  aliases and action URLs product-specific. Scholens local authentication sends
  real mail through Aliyun; there is no Mailpit profile.
- Scholens local development uses a dedicated remote dev S3 bucket with
  least-privilege development credentials. Leave `AWS_ENDPOINT_URL_S3` empty
  for AWS S3 and never point local credentials at a production bucket.
- Remote model/search providers (DeepSeek, MinerU, MOSS Voice, Scholight MCP,
  and user-configured MCP connectors) are opt-in. Use them only when the feature
  under test requires them and never commit their credentials.

## First-time setup

```bash
git clone <your-scholens-fork-url> scholens && cd scholens

# Install dependencies (first time or after lockfile changes)
cd server && uv sync
cd ../jobs && uv sync
cd ../client && corepack yarn install
cd ../web && corepack enable && pnpm install --frozen-lockfile

# Create private runtime files by copying only each service's section from
# .env.example; do not copy the complete catalog into browser runtimes.
cd ..
touch server/.env jobs/.env web/.env.local client/.env.local

# Provision identity from sanchezcloud-identity first. Then provision the local
# product owner/role and apply Scholens migrations explicitly with the migrator.
cd server
DATABASE_URL='postgresql+psycopg2://scholens_migrator:<local-password>@127.0.0.1:55432/sanchezcloud' \
  uv run python -m app.scripts.migrate_product
```

Create roles and schemas with a local database administrator following the
[sanchezcloud-identity handbook](https://github.com/EricSanchezok/sanchezcloud-identity/blob/main/docs/guides/local-development.md).
`scholens_migrator` owns and migrates the product schema; `scholens_app` is the
runtime role and must not own schemas. Alembic intentionally refuses to migrate
a `scholens` schema owned by another role. Never use the server's daily runtime
command as a migration shortcut.

## Start locally (daily)

The default profile is Server + Web. Add Jobs only for uploads, parsing,
background processing, or Zotero synchronization. The legacy client,
Storybook, and Flower are opt-in profiles.

Use separate terminals:

| Profile | Directory | Command                                                                   |
| ------- | --------- | ------------------------------------------------------------------------- |
| Default | `server/` | `uv run --frozen --no-sync start` — validate local PostgreSQL; API 7301   |
| Default | `web/`    | `pnpm dev` — canonical web on 7300                                        |
| Jobs    | `jobs/`   | `uv run --frozen --no-sync start` — broker, worker, Beat, and API 7302   |
| Legacy  | `client/` | `corepack yarn dev` — comparison UI on 7303                              |
| UI      | `web/`    | `pnpm storybook` — isolated components on 7306, no Server required        |
| Observe | `jobs/`   | `./scripts/start_flower.sh` — Flower on 7307 after RabbitMQ is available |

Check: [127.0.0.1:7301/docs](http://127.0.0.1:7301/docs),
[127.0.0.1:7300](http://127.0.0.1:7300), and, when enabled,
[127.0.0.1:7302](http://127.0.0.1:7302),
[127.0.0.1:7303](http://127.0.0.1:7303), and
[127.0.0.1:7306](http://127.0.0.1:7306). Confirm the worker log shows
`celery@... ready` when using the Jobs profile.

If any registered port is occupied, stop the conflicting process or change the
other project's contract deliberately in all affected repositories. Do not
silently select a random port, because callback URLs, CORS, cookies, tests, and
service-to-service URLs rely on these stable endpoints.

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
