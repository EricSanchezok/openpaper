#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
COMPOSE_FILE=${OPENPAPER_COMPOSE_FILE:-"${SCRIPT_DIR}/compose.yaml"}
RUNTIME_ENV=${OPENPAPER_RUNTIME_ENV:-/etc/openpaper/runtime.env}
RELEASE_ENV=${OPENPAPER_RELEASE_ENV:?OPENPAPER_RELEASE_ENV is required}

compose() {
  docker compose --env-file "${RUNTIME_ENV}" --env-file "${RELEASE_ENV}" \
    -f "${COMPOSE_FILE}" "$@"
}

retry() {
  local attempts=$1
  shift
  local count=1
  until "$@"; do
    if (( count >= attempts )); then
      return 1
    fi
    count=$((count + 1))
    sleep 3
  done
}

api_ready() {
  compose exec -T api python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3)" \
    >/dev/null
}

jobs_ready() {
  compose exec -T jobs-api python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3)" \
    >/dev/null
}

client_ready() {
  compose exec -T client node -e \
    "fetch('http://127.0.0.1:3000/healthz').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))" \
    >/dev/null
}

worker_ready() {
  compose exec -T worker celery --app src.celery_app inspect ping --timeout=5 \
    | grep -q pong
}

retry 40 api_ready
retry 40 jobs_ready
retry 40 client_ready
retry 20 worker_ready

domain=$(sed -n 's/^OPENPAPER_DOMAIN=//p' "${RUNTIME_ENV}")
[[ -n ${domain} ]] || { printf 'OPENPAPER_DOMAIN is missing\n' >&2; exit 1; }
retry 20 curl --fail --silent --show-error --max-time 10 "https://${domain}/healthz" \
  >/dev/null

printf 'OpenPaper smoke checks passed\n'
