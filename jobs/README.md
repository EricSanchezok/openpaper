# Scholens Jobs

The Jobs service runs long-lived Scholens workflows outside the API process.
Celery workers consume RabbitMQ queues, use Redis for task results and resumable
parser state, and return signed results to the Server webhook API.

## PDF ingestion

The PDF worker follows one explicit, local-first pipeline:

1. Download the original PDF from private S3 storage.
2. Analyze the PDF locally with PyMuPDF: per-page text statistics, preview,
   and deterministic page offsets (milliseconds per page).
3. Classify the document:
   - **Scanned PDF** (empty or near-empty text layer, or repeated boilerplate
     such as per-page watermarks) is submitted to MinerU, the only OCR-capable
     parser, and shares one 600-second deadline across polling and archive
     download.
   - **Digital PDF** (≥80% of uploads: arXiv, journal, most conference PDFs)
     stays local:
     a. `pymupdf4llm` extracts page-chunked Markdown with exact per-page
        offsets (primary engine);
     b. on failure, `markitdown` is tried as a second engine and is persisted
        as `text_only` because its output has no page boundaries (offsets are
        approximated from the local page analysis);
     c. if both local engines fail, MinerU rescues the document (OCR can
        recover misclassified or malformed PDFs);
     d. if the MinerU rescue fails or times out, the deterministic per-page
        text from step 2 is persisted as `text_only` with exact offsets.
4. Store Markdown and preview; only the MinerU path produces an audit archive
   (`mineru-result.zip`).
5. Extract metadata with DeepSeek unless the caller supplied authoritative
   metadata, as Zotero imports do.
6. Send the result and token usage to Server through an HMAC-signed webhook.

Local engines (`pymupdf4llm`, `markitdown`) are CPU-only, run in-process with
a bounded time budget per engine, and never send document content off-host.
MinerU is used only for scanned PDFs and as a rescue for digital PDFs whose
local extraction failed; its results are persisted as `full` quality. A
`text_only` result (local fallback or rescue timeout) is persisted so the
client can warn that layout-dependent content may be incomplete.

MinerU task IDs are checkpointed in Redis under the job ID. Four consecutive
network failures switch polling or downloading to a slower bounded backoff;
they do not end the task before its deadline. A redelivered Celery task resumes
the same provider task instead of submitting another one. The checkpoint is
cleared after Server acknowledges the result.

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
uv run --frozen --no-sync start
```

This optional profile starts RabbitMQ on `127.0.0.1:55672`, Redis on
`127.0.0.1:56379`, the worker, one Beat scheduler, and the Jobs API on
`127.0.0.1:7302`. It does not install dependencies or apply database
migrations. Run it only when exercising uploads, parsing, background work, or
Zotero synchronization. Flower is separately available on
`127.0.0.1:7307` with `./scripts/start_flower.sh`.

For object storage, Jobs uses the same isolated remote dev S3 bucket as Server,
with matching values in the two ignored `.env` files. Scholens does not start
MinIO. Never use the production bucket or production workload credentials in
the local Jobs profile.

Run an opt-in real MinerU check with a local PDF:

```bash
uv run python scripts/smoke_mineru.py "/absolute/path/to/test-paper.pdf"
```

The smoke test uses real provider quota and is intentionally excluded from CI.
It prints the `submit`, `upload`, `poll`, `download`, and `archive` stages
independently, plus safe IDs, timings, output size, and classified diagnostics.
It never prints credentials or the signed upload URL.
