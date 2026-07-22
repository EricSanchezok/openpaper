# OpenPaper production deployment

This package deploys OpenPaper to the existing SanchezCloud EC2/RDS environment. It uses the
same PostgreSQL database and `auth` schema as Scholight, while all OpenPaper-owned tables live in
an isolated `openpaper` schema. `cloud-auth` remains an in-process SDK; there is no separate auth
HTTP service to operate.

The release contains three immutable ECR images (API, client, jobs), RabbitMQ and Redis on an
internal Docker network, and API/worker/beat processes. Only the existing Caddy gateway can reach
the OpenPaper client and API over the external `sanchezcloud-edge` Docker network.

## Database boundary

- Use the same RDS database name as Scholight. Cross-database foreign keys are not possible.
- Keep `auth.*` shared. OpenPaper foreign keys point directly to `auth.users(id)`.
- Keep OpenPaper application tables in `openpaper.*` by retaining the encoded `search_path`
  option in both database URLs from `runtime.env.example`.
- Use a dedicated `openpaper_app` login for the API. It receives DML only.
- Reuse the schema-owning migration login (currently `scholight_migrator`) so both products can
  serialize and apply cloud-auth migrations. Never expose this login to the API container.

Run the bootstrap as the RDS database owner before the first migration and once again after it:

```bash
psql "$DATABASE_ADMIN_URL" \
  -v app_role=openpaper_app \
  -v migrator_role=scholight_migrator \
  -f deploy/production/bootstrap-db.sql
```

The migration container always applies cloud-auth first, then OpenPaper Alembic migrations. Both
runners use PostgreSQL advisory locks. Normal releases never run down migrations; migrations must
therefore remain compatible with the immediately previous application release.

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
