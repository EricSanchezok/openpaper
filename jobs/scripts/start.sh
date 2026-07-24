#!/bin/bash
# Setup dependencies in a virtual environment.
uv sync
source .venv/bin/activate

# Pin local infrastructure versions so a new upstream `latest` release cannot
# silently break Celery's queue declarations.
docker start op-rabbitmq 2>/dev/null || docker run -d --name op-rabbitmq -p 5672:5672 rabbitmq:3.13-alpine
docker start op-redis 2>/dev/null || docker run -d --name op-redis -p 6379:6379 redis:7-alpine

# Start Celery worker
./scripts/start_worker.sh &

# Start Celery Beat scheduler for periodic tasks (e.g. Zotero auto-sync).
# Bundled here for local dev so it doesn't need a separate command; run only a
# single Beat instance (don't launch start_beat.sh separately alongside this).
./scripts/start_beat.sh &

# Start worker API
./scripts/start_api.sh
