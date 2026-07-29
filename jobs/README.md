# Scholens Jobs

The Jobs service runs long-lived Scholens workflows outside the API process.
Celery workers consume RabbitMQ queues, use Redis for task results and resumable
parser state, and return signed results to the Server webhook API.

## PDF ingestion

The PDF worker follows one explicit pipeline:

1. Download the original PDF from private S3 storage.
2. Generate a short-lived S3 URL for MinerU.
3. Analyze the local PDF with PyMuPDF for preview and deterministic page text.
4. Submit or resume the MinerU task and share one 600-second deadline across
   polling and archive download.
5. Validate and normalize MinerU's archive into canonical Markdown.
6. If the MinerU lifecycle reaches that deadline, accept PyMuPDF text only when
   it passes the local quality gate.
7. Store Markdown, preview, and the MinerU archive when available.
8. Extract metadata with DeepSeek unless the caller supplied authoritative
   metadata, as Zotero imports do.
9. Send the result and token usage to Server through an HMAC-signed webhook.

MinerU is the only high-fidelity parser. PyMuPDF is a deterministic fallback for
native-text PDFs; it does not attempt OCR, table reconstruction, or formula
recognition. A fallback result is persisted as `text_only` so the client can
warn that layout-dependent content may be incomplete.

MinerU task IDs are checkpointed in Redis under the job ID. Four consecutive
network failures switch polling or downloading to a slower bounded backoff;
they do not end the task before its deadline. A redelivered Celery task resumes
the same provider task instead of submitting another one.

When a running MinerU task outlives the initial deadline, Scholens keeps its
checkpoint after persisting the `text_only` result. A dedicated Celery task
continues the existing MinerU lifecycle. Once the full result is available,
Jobs writes deterministic Markdown and audit ZIP keys and Server atomically
replaces the paper content, page offsets, parser quality, and passage index.
The checkpoint is cleared only after Server acknowledges the full result.

## Code layout

```text
src/
├── pdf/
│   ├── models.py    # Parse results and classified errors
│   ├── mineru.py    # MinerU lifecycle, archive security, normalization
│   ├── local.py     # PyMuPDF analysis and fallback
│   ├── state.py     # Redis task checkpoint and submit lock
│   └── pipeline.py  # Parser selection, S3 artifacts, metadata
├── tasks.py         # Thin Celery task adapters
├── llm_client.py    # DeepSeek jobs client
├── s3_service.py
└── webhook_signing.py
```

Parser-specific tests mirror this structure under `tests/pdf/`.

## Configuration

The repository-level [`.env.example`](../.env.example) is the only environment
variable catalog. Copy the values needed by Jobs into `jobs/.env`; never commit
that file.

Production requires:

- RabbitMQ through `CELERY_BROKER_URL`
- Redis through `CELERY_RESULT_BACKEND` and optionally `PDF_PARSE_REDIS_URL`
- S3 credentials and bucket names
- `MINERU_API_TOKEN`
- `DEEPSEEK_API_KEY`
- `JOBS_WEBHOOK_SIGNING_SECRET`

Development may omit `MINERU_API_TOKEN`; PDF ingestion then runs explicitly in
local `text_only` mode. Production fails fast when the token or parser Redis
configuration is absent.

## Local commands

Install and verify:

```bash
uv sync
uv run ruff check src tests
uv run mypy src/pdf src/schemas.py src/tasks.py
uv run pytest -q
```

Start the local stack:

```bash
uv run start
```

Run an opt-in real MinerU check with a local PDF:

```bash
uv run python scripts/smoke_mineru.py "/absolute/path/to/test-paper.pdf"
```

The smoke test uses real provider quota and is intentionally excluded from CI.
It prints the `submit`, `upload`, `poll`, `download`, and `archive` stages
independently, plus safe IDs, timings, output size, and classified diagnostics.
It never prints credentials or the signed upload URL.
