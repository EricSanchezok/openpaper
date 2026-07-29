"""Opt-in MinerU smoke test; never run by the default test suite."""

from __future__ import annotations

import argparse
import asyncio
import time
import uuid
from pathlib import Path

from src.pdf.mineru import MinerUClient
from src.pdf.models import ParserError


async def run(source_file: Path) -> None:
    job_id = f"smoke-{uuid.uuid4().hex}"
    client = MinerUClient()
    pdf_bytes = source_file.read_bytes()
    started_at = time.monotonic()
    last_phase_at = started_at

    def report_phase(phase: str, task_id: str | None) -> None:
        nonlocal last_phase_at
        now = time.monotonic()
        task_suffix = f" task_id={task_id}" if task_id else ""
        print(
            f"[{phase}] started",
            f"elapsed={now - started_at:.1f}s",
            f"previous_phase={now - last_phase_at:.1f}s",
            task_suffix,
            flush=True,
        )
        last_phase_at = now

    try:
        result = await client.parse_file(
            pdf_bytes,
            data_id=job_id,
            phase_callback=report_phase,
        )
        print(
            "[complete] MinerU smoke test passed:",
            f"backend={result.backend.value}",
            f"version={result.parser_version}",
            f"characters={len(result.markdown)}",
            f"pages={len(result.page_offset_map)}",
            f"archive_bytes={len(result.archive_bytes or b'')}",
            f"elapsed={time.monotonic() - started_at:.1f}s",
            flush=True,
        )
        await client.state_store.clear(job_id)
    except ParserError as exc:
        diagnostics = " ".join(
            f"{key}={value}" for key, value in exc.diagnostic_fields().items()
        )
        print(
            "[failed] MinerU smoke test failed:",
            diagnostics or f"exception_type={type(exc).__name__}",
            f"elapsed={time.monotonic() - started_at:.1f}s",
            flush=True,
        )
        raise
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload one local PDF through MinerU's signed batch API."
    )
    parser.add_argument("source_file", type=Path, help="Path to a local PDF")
    args = parser.parse_args()
    asyncio.run(run(args.source_file))


if __name__ == "__main__":
    main()
