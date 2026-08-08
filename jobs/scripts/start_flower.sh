#!/usr/bin/env bash
set -euo pipefail

# Start Flower monitoring dashboard
echo "Starting Flower dashboard..."
jobs_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python_bin="$jobs_root/.venv/bin/python"
if [[ ! -x "$python_bin" ]]; then
    echo "Jobs virtual environment is missing; run 'uv sync --frozen --group dev'." >&2
    exit 1
fi
cd "$jobs_root"
exec "$python_bin" -m celery --app src.celery_app flower --address=127.0.0.1 --port=7307
