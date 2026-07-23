#!/usr/bin/env bash
set -euo pipefail

command_id=${1:?command id is required}
instance_id=${2:?instance id is required}
region=${AWS_REGION:?AWS_REGION is required}

for _ in $(seq 1 120); do
  status=$(aws ssm get-command-invocation \
    --command-id "${command_id}" \
    --instance-id "${instance_id}" \
    --region "${region}" \
    --query Status --output text 2>/dev/null || true)
  case "${status}" in
    Success)
      aws ssm get-command-invocation --command-id "${command_id}" \
        --instance-id "${instance_id}" --region "${region}" \
        --query StandardOutputContent --output text
      exit 0
      ;;
    Failed|TimedOut|Cancelled|Cancelling)
      aws ssm get-command-invocation --command-id "${command_id}" \
        --instance-id "${instance_id}" --region "${region}" \
        --query '{stdout:StandardOutputContent,stderr:StandardErrorContent}' --output json
      exit 1
      ;;
  esac
  sleep 5
done

printf 'SSM command timed out: %s\n' "${command_id}" >&2
exit 1
