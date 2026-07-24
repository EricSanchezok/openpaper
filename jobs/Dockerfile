ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b
FROM ${PYTHON_IMAGE} AS builder

RUN python -m pip install --no-cache-dir uv==0.9.2
WORKDIR /app
COPY jobs/pyproject.toml jobs/uv.lock jobs/README.md /app/
RUN uv sync --frozen --no-dev --no-install-project
COPY jobs/src/ /app/src/
RUN uv pip install --no-deps /app

FROM ${PYTHON_IMAGE} AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 scholens

WORKDIR /app
COPY --from=builder /app/.venv/ /app/.venv/
COPY --from=builder /app/src/ /app/src/

ENV PATH=/app/.venv/bin:$PATH
USER scholens
EXPOSE 8001

CMD ["python", "-m", "uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8001"]
