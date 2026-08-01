#!/usr/bin/env bash
set -euo pipefail

APPLICATION_NAME=${APPLICATION_NAME:-scholens}
ENVIRONMENT_NAME=${ENVIRONMENT_NAME:-production}
AGENT_VERSION=${CLOUDWATCH_AGENT_VERSION:?Set CLOUDWATCH_AGENT_VERSION to an approved package version}
REGION=${AWS_REGION:?Set AWS_REGION}

if [[ $(id -u) -ne 0 ]]; then
  printf 'Run this script as root\n' >&2
  exit 1
fi

if command -v dnf >/dev/null 2>&1; then
  dnf install -y "amazon-cloudwatch-agent-${AGENT_VERSION}"
elif command -v yum >/dev/null 2>&1; then
  yum install -y "amazon-cloudwatch-agent-${AGENT_VERSION}"
else
  printf 'This installer supports RPM-based EC2 hosts\n' >&2
  exit 1
fi

install -d -m 0750 /etc/scholens/observability
aws ssm get-parameter \
  --region "${REGION}" \
  --name "/${APPLICATION_NAME}/${ENVIRONMENT_NAME}/cloudwatch-agent/config" \
  --query 'Parameter.Value' \
  --output text > /etc/scholens/observability/agent.json
aws ssm get-parameter \
  --region "${REGION}" \
  --name "/${APPLICATION_NAME}/${ENVIRONMENT_NAME}/cloudwatch-agent/otel" \
  --query 'Parameter.Value' \
  --output text > /etc/scholens/observability/otel.yaml
chmod 0640 /etc/scholens/observability/agent.json /etc/scholens/observability/otel.yaml

/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config \
  -m ec2 \
  -c file:/etc/scholens/observability/agent.json \
  -s
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a append-config \
  -m ec2 \
  -c file:/etc/scholens/observability/otel.yaml \
  -s

systemctl enable amazon-cloudwatch-agent
systemctl --no-pager --full status amazon-cloudwatch-agent
