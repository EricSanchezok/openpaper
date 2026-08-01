# AWS observability setup

This runbook installs the production resources required by Scholens structured
logs, OpenTelemetry traces and metrics, CloudWatch RUM, alarms, and encrypted
diagnostic snapshots. It does not create, migrate, inspect, or modify RDS.

## 1. Review and deploy the stack

Before deployment, review
`deploy/production/observability.yaml`. The stack attaches a least-privilege
inline policy to an existing EC2 instance role, so pass the role **name**, not
its ARN.

```bash
aws cloudformation validate-template \
  --template-body file://deploy/production/observability.yaml

aws cloudformation deploy \
  --stack-name scholens-production-observability \
  --template-file deploy/production/observability.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ApplicationName=scholens \
    EnvironmentName=production \
    DomainName=scholens.example.com \
    InstanceRoleName=EXISTING_EC2_ROLE_NAME \
    AlertEmail=operator@example.com \
    BreakGlassPrincipalArn=arn:aws:iam::ACCOUNT_ID:role/EXISTING_SECURITY_OPERATOR_ROLE \
    MonthlyCloudWatchBudgetUsd=50
```

Confirm the SNS subscription sent to `AlertEmail`; unconfirmed subscriptions
cannot deliver alarms. Keep the stack outputs:

```bash
aws cloudformation describe-stacks \
  --stack-name scholens-production-observability \
  --query 'Stacks[0].Outputs' \
  --output table
```

The diagnostic bucket is KMS-encrypted, unversioned, private, and expires every
object after seven days. The application role has `PutObject` only. Reading or
deleting a snapshot requires assuming the stack-created break-glass role, whose
S3 object data events are written by CloudTrail to a separate private audit
bucket for 30 days. Confirm that `BreakGlassPrincipalArn` names an existing
human-operated security role rather than an application role. Source maps are
private, expire after 30 days, and can only be read by the matching RUM app
monitor through `aws:SourceAccount` and `aws:SourceArn` conditions.

## 2. Install the host CloudWatch Agent

Choose and record an approved CloudWatch Agent RPM version. Do not use an
unpinned `latest` download in production.

```bash
dnf --showduplicates list amazon-cloudwatch-agent
sudo env \
  AWS_REGION=us-east-1 \
  CLOUDWATCH_AGENT_VERSION=APPROVED_VERSION \
  APPLICATION_NAME=scholens \
  ENVIRONMENT_NAME=production \
  deploy/production/install-observability.sh
```

The installer fetches the reviewed host and OpenTelemetry configurations from
SSM Parameter Store. The agent listens for OTLP/gRPC on host port 4317 and
sends application metrics to CloudWatch and traces to X-Ray. The EC2 security
group must not expose 4317; it is for local Docker-to-host traffic only.
The stack enables X-Ray Transaction Search and Application Signals discovery,
so every trace accepted from the application's own sampler is indexed for the
Application Signals service map. This 100% indexing applies only after the
application's one-per-second-plus-ten-percent trace sampling, not to every
production request.
Each process keeps a one-root-trace-per-second reservoir and samples ten
percent of the remaining root traces; child spans honor the parent decision.
Structured error logs and failure counters remain unsampled.

Verify:

```bash
systemctl is-active amazon-cloudwatch-agent
ss -lnt | grep ':4317'
journalctl -u amazon-cloudwatch-agent --since '10 minutes ago'
```

## 3. Configure the Scholens runtime

Copy the stack outputs into `/etc/scholens/runtime.env`:

```dotenv
SCHOLENS_OTEL_EXPORTER_OTLP_ENDPOINT=host.docker.internal:4317
SCHOLENS_DIAGNOSTIC_SNAPSHOT_BUCKET=STACK_OUTPUT_DiagnosticBucketName
SCHOLENS_DIAGNOSTIC_SNAPSHOT_KMS_KEY_ID=STACK_OUTPUT_DiagnosticKmsKeyArn
SCHOLENS_DIAGNOSTIC_SUCCESS_SAMPLE_RATE=0.01
```

The API and jobs processes emit JSON to stdout. Docker's `awslogs` driver sends
each service to a separate 30-day CloudWatch log group. Do not put AWS access
keys in the runtime file; the Docker daemon, CloudWatch Agent, API, and jobs use
the EC2 instance role.
Production startup fails if either diagnostic snapshot value is absent; this is
a deployment configuration error rather than a runtime condition to hide.

After changing the runtime file, deploy a normal immutable release. Confirm
that these groups receive events:

- `/scholens/production/api`
- `/scholens/production/client`
- `/scholens/production/jobs-api`
- `/scholens/production/worker`
- `/scholens/production/beat`
- `/scholens/production/rabbitmq`
- `/scholens/production/redis`
- `/scholens/production/otel-metrics`

## 4. Configure RUM and source maps

Set the following GitHub Actions variables from stack outputs:

- `NEXT_PUBLIC_RUM_APPLICATION_ID` = `RumApplicationId`
- `NEXT_PUBLIC_RUM_GUEST_ROLE_ARN` = `RumGuestRoleArn`
- `NEXT_PUBLIC_RUM_IDENTITY_POOL_ID` = `RumIdentityPoolId`
- `RUM_SOURCE_MAP_BUCKET` = `SourceMapBucketName`
- `AWS_REGION` = the stack region

The release workflow builds source maps with the same release SHA embedded in
the browser bundle, checks CloudWatch's 50 MiB per-map limit, and uploads only
`.map` files to `s3://BUCKET/RELEASE_SHA/`. Source maps are never copied into
the runtime image's public static directory. The GitHub publish role needs
`s3:PutObject` for that bucket prefix.

RUM samples 100% of sessions, records errors, performance and HTTP telemetry,
and sends custom error events containing only bounded technical identifiers.
RUM cookies are disabled. It does not record API request/response bodies,
resource URLs, credentials, or user prompts. Page IDs contain paths only, and
the browser SDK excludes any HTTP URL containing a query or fragment; those
failures are still counted by the shared URL-free API error reporter. PostHog remains the product
analytics system; it is not used for technical exception diagnosis.

## 5. Verify correlation end to end

1. Open the application and execute one successful request and one known 4xx.
2. Confirm the response contains `X-Request-ID` and, after authentication,
   `X-Correlation-ID`.
3. Search the API log group for the request ID.
4. Open the correlated X-Ray trace and confirm SQL, dependency, LLM/tool, and
   workflow spans contain no request bodies, query strings, or secrets.
5. Trigger a controlled authenticated error and verify its public
   `diagnostic_id` maps to one encrypted S3 object.
6. Open the `${ApplicationName}-${EnvironmentName}` dashboard and verify RUM,
   backend, jobs, and host data.

Example Logs Insights query:

```text
fields @timestamp, service, event, error_code, request_id, correlation_id, diagnostic_id
| filter correlation_id = "CORRELATION_ID"
| sort @timestamp asc
```

## 6. Failure and cost controls

- A CloudWatch, X-Ray, RUM, or S3 outage must not fail a business operation.
  Diagnostic writes use a bounded background queue and fail open.
- A full diagnostic writer queue emits `diagnostic.snapshot.dropped`; an S3
  failure emits `diagnostic.snapshot.write_failed` and triggers an alarm.
- All runtime failure snapshots and authenticated business errors are captured.
  Eligible successes use deterministic 1% sampling.
- Metrics labels are low-cardinality. Request, user, conversation, task, and
  operation IDs belong in logs/traces, never metric dimensions.
- Review RUM 100% sampling and log volume monthly. Reduce the RUM sample only
  through an explicit product/operations decision, not an emergency code fork.
- The stack creates a forecasted monthly CloudWatch budget and emails
  `AlertEmail` when forecast spend reaches `MonthlyCloudWatchBudgetUsd`. It also
  alarms on the combined API 5xx count/rate, terminal stream failures, worker
  heartbeat loss, queue age, dependency failures, LLM timeout rate, unknown
  token usage, diagnostic write failures, and browser error rate.

Diagnostic snapshots are mandatory in production. To disable them during an
incident, deploy an explicit reviewed code/configuration change; removing the
bucket or KMS values deliberately fails startup. To disable telemetry export,
remove `SCHOLENS_OTEL_EXPORTER_OTLP_ENDPOINT`; structured local logs and stable
error responses continue to work.
