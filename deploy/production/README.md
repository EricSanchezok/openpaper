# Scholens production deployment

This package deploys Scholens to the existing SanchezCloud EC2/RDS environment. It uses the
same PostgreSQL database and `auth` schema as Scholight, while all Scholens-owned tables live in
an isolated `scholens` schema. `sanchezcloud-identity` remains an in-process SDK; there is no separate auth
HTTP service to operate.

The release contains three immutable ECR images (API, client, jobs), RabbitMQ and Redis on an
internal Docker network, and API/worker/beat processes. Only the existing Caddy gateway can reach
the Scholens client and API over the external `sanchezcloud-edge` Docker network.

## Database boundary

- Use the shared `sanchezcloud` database. Cross-database foreign keys are not possible.
- `sanchezcloud-identity` alone owns `auth.*`; Scholens only references `auth.users(id)`.
- Scholens alone owns `scholens.*`; models and migrations qualify this schema explicitly.
- Use a dedicated `scholens_app` login for the API. It receives DML only.
- Use `auth_migrator` only for `auth.*` and `scholens_migrator` only for
  `scholens.*`. Neither role receives database-level `CREATE`.

Run the bootstrap as the RDS database owner before the first migration and once again after it:

```bash
psql "$DATABASE_ADMIN_URL" \
  -v app_role=scholens_app \
  -v auth_migrator_role=auth_migrator \
  -v product_migrator_role=scholens_migrator \
  -f deploy/production/bootstrap-db.sql
```

Run this bootstrap before sanchezcloud-identity migration, after sanchezcloud-identity migration, and
after Scholens migration. The sanchezcloud-identity repository independently migrates
`auth.*`; the Scholens migration container checks the auth ledger and applies
only `scholens.*`. Both runners use PostgreSQL advisory locks.

The `/admin` login uses an ordinary verified sanchezcloud-identity account and then checks
`scholens.user_profiles.is_admin`. Bootstrap the first administrator out of band
after that account registers:

```sql
INSERT INTO scholens.user_profiles (user_id, is_admin)
SELECT id, true FROM auth.users WHERE lower(email) = lower('operator@example.com')
ON CONFLICT (user_id) DO UPDATE SET is_admin = true;
```

`SCHOLENS_ADMIN_SESSION_SECRET` only signs the admin browser session; it is not
an administrator password.

Scholens and Scholight may use the same Aliyun DirectMail account credentials.
Keep `SCHOLENS_ALIYUN_DM_FROM_ALIAS` and the Scholens public URL
product-specific so verification and password-reset links return to the correct
frontend. The two products also keep independent JWT secrets and refresh-token
audiences even though both authenticate against `auth.users`.

## One-time host setup

The host needs Docker Engine, Compose v2, AWS CLI, `curl`, `flock`, and SSM connectivity. Its EC2
instance role needs ECR pull, SSM managed-instance, and least-privilege access to the Scholens S3
bucket.

```bash
sudo install -d -m 0755 /opt/scholens /etc/scholens /var/lib/scholens
docker network inspect sanchezcloud-edge >/dev/null 2>&1 || \
  docker network create sanchezcloud-edge
sudo install -m 0644 deploy/production/compose.yaml /opt/scholens/compose.yaml
sudo install -m 0600 deploy/production/bootstrap-db.sql /opt/scholens/bootstrap-db.sql
sudo install -m 0755 deploy/production/release.sh /opt/scholens/release.sh
sudo install -m 0755 deploy/production/smoke.sh /opt/scholens/smoke.sh
sudo install -m 0755 deploy/production/wait-ssm.sh /opt/scholens/wait-ssm.sh
sudo install -m 0755 deploy/production/install-observability.sh /opt/scholens/install-observability.sh
sudo install -m 0755 deploy/production/upload-source-maps.sh /opt/scholens/upload-source-maps.sh
sudo install -m 0644 deploy/production/observability.yaml /opt/scholens/observability.yaml
sudo install -m 0600 deploy/production/runtime.env.example /etc/scholens/runtime.env
sudoedit /etc/scholens/runtime.env
```

Copy the AWS RDS global CA bundle already used by Scholight to
`/etc/scholens/global-bundle.pem`, owned by root and readable by Docker. Install the accompanying
Caddy configuration through the Scholight deployment package; it is the component that owns
ports 80/443 and TLS certificates.

Do not store static AWS access keys in `runtime.env`. The server and jobs images let the AWS SDK
use the EC2 instance role.

Deploy CloudWatch, X-Ray, RUM, alarms, KMS/S3 diagnostic storage, and the host
agent by following [the observability runbook](../../docs/operations/AWS_OBSERVABILITY_SETUP.md).

## AWS and GitHub setup

Create three immutable, scan-on-push ECR repositories:

- `scholens/api`
- `scholens/client`
- `scholens/jobs`

Configure GitHub OIDC roles instead of access keys. Repository/environment variables used by the
release workflow are:

- `AWS_REGION`, `AWS_PUBLISH_ROLE_ARN`, `AWS_DEPLOY_ROLE_ARN`
- `ECR_API_REPOSITORY`, `ECR_CLIENT_REPOSITORY`, `ECR_JOBS_REPOSITORY`
- `PRODUCTION_PLATFORM` (`linux/amd64` or `linux/arm64`)
- `PRODUCTION_INSTANCE_ID`
- public build values `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`, `NEXT_PUBLIC_POSTHOG_KEY`, and
  `NEXT_PUBLIC_POSTHOG_HOST`
- `NEXT_PUBLIC_RUM_APPLICATION_ID`, `NEXT_PUBLIC_RUM_GUEST_ROLE_ARN`,
  `NEXT_PUBLIC_RUM_IDENTITY_POOL_ID`, and `RUM_SOURCE_MAP_BUCKET` from the
  observability stack outputs

Add `CLOUD_AUTH_READ_TOKEN` as a read-only repository secret. Protect the GitHub `production`
environment with required reviewers. The publish role may push only to the three ECR repositories;
the deploy role may send and inspect SSM commands only for the production instance.

Configure `SCHOLENS_CONNECTOR_CREDENTIAL_ENCRYPTION_KEY` and
`SCHOLENS_SCHOLIGHT_MCP_DELEGATION_JWT_SECRET` in
`/etc/scholens/runtime.env`. The encryption key is URL-safe base64 for exactly
32 random bytes. The delegation secret must match Scholight's
`SCHOLIGHT_MCP_DELEGATION_JWT_SECRET`; Scholens signs a short-lived,
user-scoped token for
each MCP call. External provider API keys are connected per user in Settings
and are never process environment variables.

## Deploy and rollback

Use the `Release` GitHub workflow. `publish` builds digest-addressed images, `deploy` additionally
activates them through SSM, and `rollback` restores the previous coordinated image set.

The host command used by the workflow is:

```bash
sudo /opt/scholens/release.sh deploy \
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
the previous image set and saves logs under `/var/lib/scholens/failed/<git-sha>/`.

```bash
sudo /opt/scholens/release.sh rollback
sudo /opt/scholens/release.sh status
```

An interrupted activation leaves `/var/lib/scholens/transition.env` and blocks subsequent
operations. Compare the running image digests with `current.env`, restore either the current or
target manifest deliberately, run `smoke.sh`, and only then remove the transition journal.
