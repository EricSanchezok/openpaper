#!/usr/bin/env bash
set -euo pipefail

jobs_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$jobs_root"

docker compose -f compose.local.yaml up -d rabbitmq redis

child_pids=()
cleanup() {
    trap - EXIT INT TERM
    if ((${#child_pids[@]})); then
        kill "${child_pids[@]}" 2>/dev/null || true
        wait "${child_pids[@]}" 2>/dev/null || true
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Start Celery worker
./scripts/start_worker.sh &
child_pids+=("$!")

# Start Celery Beat scheduler for periodic tasks (e.g. Zotero auto-sync).
# Bundled here for local dev so it doesn't need a separate command; run only a
# single Beat instance (don't launch start_beat.sh separately alongside this).
./scripts/start_beat.sh &
child_pids+=("$!")

# Start worker API
./scripts/start_api.sh
