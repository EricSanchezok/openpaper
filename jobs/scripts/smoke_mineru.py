"""Opt-in MinerU smoke test; never run by the default test suite."""

from __future__ import annotations

import argparse
import asyncio
import uuid

from src.pdf.mineru import MinerUClient


async def run(source_url: str) -> None:
    job_id = f"smoke-{uuid.uuid4().hex}"
    client = MinerUClient()
    try:
        result = await client.parse_url(source_url, data_id=job_id)
        print(
            "MinerU smoke test passed:",
            f"backend={result.backend.value}",
            f"version={result.parser_version}",
            f"characters={len(result.markdown)}",
            f"pages={len(result.page_offset_map)}",
        )
        await client.state_store.clear(job_id)
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Submit one externally reachable PDF URL to MinerU."
    )
    parser.add_argument("source_url", help="A temporary HTTPS URL for a test PDF")
    args = parser.parse_args()
    asyncio.run(run(args.source_url))


if __name__ == "__main__":
    main()
