# OpenPaper production deployment

This package deploys OpenPaper to the existing SanchezCloud EC2/RDS environment. It uses the
same PostgreSQL database and `auth` schema as Scholight, while all OpenPaper-owned tables live in
an isolated `openpaper` schema. `cloud-auth` remains an in-process SDK; there is no separate auth
HTTP service to operate.

The release contains three immutable ECR images (API, client, jobs), RabbitMQ and Redis on an
internal Docker network, and API/worker/beat processes. Only the existing Caddy gateway can reach
the OpenPaper client and API over the external `sanchezcloud-edge` Docker network.

## Database boundary

- Use the shared `sanchezcloud` database. Cross-database foreign keys are not possible.
- `cloud-auth` alone owns `auth.*`; OpenPaper only references `auth.users(id)`.
- OpenPaper alone owns `openpaper.*`; models and migrations qualify this schema explicitly.
- Use a dedicated `openpaper_app` login for the API. It receives DML only.
- Use `auth_migrator` only for `auth.*` and `openpaper_migrator` only for
  `openpaper.*`. Neither role receives database-level `CREATE`.

Run the bootstrap as the RDS database owner before the first migration and once again after it:

```bash
psql "$DATABASE_ADMIN_URL" \
  -v app_role=openpaper_app \
  -v auth_migrator_role=auth_migrator \
  -v product_migrator_role=openpaper_migrator \
  -f deploy/production/bootstrap-db.sql
```

Run this bootstrap before cloud-auth migration, after cloud-auth migration, and
after OpenPaper migration. The cloud-auth repository independently migrates
`auth.*`; the OpenPaper migration container checks the auth ledger and applies
only `openpaper.*`. Both runners use PostgreSQL advisory locks.

The `/admin` login uses an ordinary verified cloud-auth account and then checks
`openpaper.user_profiles.is_admin`. Bootstrap the first administrator out of band
after that account registers:

```sql
INSERT INTO openpaper.user_profiles (user_id, is_admin)
SELECT id, true FROM auth.users WHERE lower(email) = lower('operator@example.com')
ON CONFLICT (user_id) DO UPDATE SET is_admin = true;
```

`OPENPAPER_ADMIN_SESSION_SECRET` only signs the admin browser session; it is not
an administrator password.

OpenPaper and Scholight may use the same Aliyun DirectMail account credentials.
Keep `OPENPAPER_ALIYUN_DM_FROM_ALIAS` and the OpenPaper public URL
product-specific so verification and password-reset links return to the correct
frontend. The two products also keep independent JWT secrets and refresh-token
audiences even though both authenticate against `auth.users`.

## One-time host setup

The host needs Docker Engine, Compose v2, AWS CLI, `curl`, `flock`, and SSM connectivity. Its EC2
instance role needs ECR pull, SSM managed-instance, and least-privilege access to the OpenPaper S3
bucket.

```bash
sudo install -d -m 0755 /opt/openpaper /etc/openpaper /var/lib/openpaper
docker network inspect sanchezcloud-edge >/dev/null 2>&1 || \
  docker network create sanchezcloud-edge
sudo install -m 0644 deploy/production/compose.yaml /opt/openpaper/compose.yaml
sudo install -m 0600 deploy/production/bootstrap-db.sql /opt/openpaper/bootstrap-db.sql
sudo install -m 0755 deploy/production/release.sh /opt/openpaper/release.sh
sudo install -m 0755 deploy/production/smoke.sh /opt/openpaper/smoke.sh
sudo install -m 0755 deploy/production/wait-ssm.sh /opt/openpaper/wait-ssm.sh
sudo install -m 0600 deploy/production/runtime.env.example /etc/openpaper/runtime.env
sudoedit /etc/openpaper/runtime.env
```

Copy the AWS RDS global CA bundle already used by Scholight to
`/etc/openpaper/global-bundle.pem`, owned by root and readable by Docker. Install the accompanying
Caddy configuration through the Scholight deployment package; it is the component that owns
ports 80/443 and TLS certificates.

Do not store static AWS access keys in `runtime.env`. The server and jobs images let the AWS SDK
use the EC2 instance role.

## AWS and GitHub setup

Create three immutable, scan-on-push ECR repositories:

- `openpaper/api`
- `openpaper/client`
- `openpaper/jobs`

Configure GitHub OIDC roles instead of access keys. Repository/environment variables used by the
release workflow are:

- `AWS_REGION`, `AWS_PUBLISH_ROLE_ARN`, `AWS_DEPLOY_ROLE_ARN`
- `ECR_API_REPOSITORY`, `ECR_CLIENT_REPOSITORY`, `ECR_JOBS_REPOSITORY`
- `PRODUCTION_PLATFORM` (`linux/amd64` or `linux/arm64`)
- `PRODUCTION_INSTANCE_ID`
- public build values `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`, `NEXT_PUBLIC_POSTHOG_KEY`, and
  `NEXT_PUBLIC_POSTHOG_HOST`

Add `CLOUD_AUTH_READ_TOKEN` as a read-only repository secret. Protect the GitHub `production`
environment with required reviewers. The publish role may push only to the three ECR repositories;
the deploy role may send and inspect SSM commands only for the production instance.

Configure `OPENPAPER_ANYSEARCH_API_KEY` and a dedicated
`OPENPAPER_SCHOLIGHT_ACCESS_KEY` in `/etc/openpaper/runtime.env`. The Scholight
credential is a scoped `sk_live_...` search Access Key, not either product's JWT.
The corresponding MCP URLs default to the public AnySearch and SanchezCloud
Scholight Streamable HTTP endpoints.

## Deploy and rollback

Use the `Release` GitHub workflow. `publish` builds digest-addressed images, `deploy` additionally
activates them through SSM, and `rollback` restores the previous coordinated image set.

The host command used by the workflow is:

```bash
sudo /opt/openpaper/release.sh deploy \
  --contract-version 1 \
  --package-sha "$PACKAGE_SHA" \
  --release-sha "$GIT_SHA" \
  --api-image "$API_IMAGE" \
  --client-image "$CLIENT_IMAGE" \
  --jobs-image "$JOBS_IMAGE"
```

The release transaction validates the reviewed package checksum and runtime-file permissions,
pulls all images before mutation, runs migrations, activates the coordinated set, and performs
internal API/client/jobs/worker checks plus an external HTTPS check. A failed candidate restores
the previous image set and saves logs under `/var/lib/openpaper/failed/<git-sha>/`.

```bash
sudo /opt/openpaper/release.sh rollback
sudo /opt/openpaper/release.sh status
```

An interrupted activation leaves `/var/lib/openpaper/transition.env` and blocks subsequent
operations. Compare the running image digests with `current.env`, restore either the current or
target manifest deliberately, run `smoke.sh`, and only then remove the transition journal.
