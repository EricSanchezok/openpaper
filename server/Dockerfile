ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b
FROM ${PYTHON_IMAGE} AS builder

ARG SANCHEZCLOUD_IDENTITY_REVISION=6acd693b52257a229cfb84b5ad252fb6d7a5d263
ARG SANCHEZCLOUD_IDENTITY_ARCHIVE=https://api.github.com/repos/EricSanchezok/sanchezcloud-identity/tarball

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir uv==0.9.2

WORKDIR /app
RUN --mount=type=secret,id=github_token \
    mkdir -p /app/sanchezcloud-identity \
    && curl --fail --location --silent --show-error \
        --header "Authorization: Bearer $(tr -d '\n' </run/secrets/github_token)" \
        --header "X-GitHub-Api-Version: 2022-11-28" \
        --output /tmp/sanchezcloud-identity.tar.gz \
        "${SANCHEZCLOUD_IDENTITY_ARCHIVE}/${SANCHEZCLOUD_IDENTITY_REVISION}" \
    && tar -xzf /tmp/sanchezcloud-identity.tar.gz --strip-components=1 -C /app/sanchezcloud-identity \
    && rm /tmp/sanchezcloud-identity.tar.gz

COPY packages/scholens_observability/ /packages/scholens_observability/
COPY server/pyproject.toml server/uv.lock server/README.md /app/
RUN uv sync --frozen --no-dev --no-install-project --no-install-package sanchezcloud-identity \
    && uv pip install --no-deps /app/sanchezcloud-identity/

COPY server/app/ /app/app/
COPY server/migrations/ /app/migrations/
COPY server/alembic.ini server/gunicorn.config.py /app/
RUN uv pip install --no-deps /app

FROM ${PYTHON_IMAGE} AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 scholens

WORKDIR /app
COPY --from=builder /app/.venv/ /app/.venv/
COPY --from=builder /app/app/ /app/app/
COPY --from=builder /app/migrations/ /app/migrations/
COPY --from=builder /app/alembic.ini /app/gunicorn.config.py /app/

ENV PATH=/app/.venv/bin:$PATH \
    ENVIRONMENT=production \
    PORT=8000

USER scholens
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/livez', timeout=3)"

CMD ["gunicorn", "-c", "gunicorn.config.py", "app.main:app"]
