#!/usr/bin/env bash
set -euo pipefail

# Start Celery Beat scheduler for periodic tasks (e.g. Zotero auto-sync).
# Run this as a single separate process - do NOT run multiple instances.
echo "Starting Celery Beat scheduler..."
jobs_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python_bin="$jobs_root/.venv/bin/python"
if [[ ! -x "$python_bin" ]]; then
    echo "Jobs virtual environment is missing; run 'uv sync --frozen --group dev'." >&2
    exit 1
fi
cd "$jobs_root"

exec "$python_bin" -m celery --app src.celery_app beat --loglevel=info
