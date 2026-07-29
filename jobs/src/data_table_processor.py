import asyncio
import logging
from typing import Callable

from src.llm_client import llm_client
from src.schemas import (
    DataTableCellValue,
    DataTableResult,
    DataTableRow,
    DataTableSchema,
    DocumentMapping,
)


logger = logging.getLogger(__name__)

# Maximum number of concurrent paper extractions
DEFAULT_BATCH_SIZE = 5


async def _process_single_paper(
    paper: DocumentMapping,
    columns: list[str],
    status_callback: Callable[[str], None],
    semaphore: asyncio.Semaphore,
) -> tuple[DataTableRow, str | None]:
    """
    Process a single paper extraction with semaphore-controlled concurrency.

    Args:
        paper: The paper to process
        columns: Column names to extract
        status_callback: Callback for status updates
        semaphore: Semaphore to control concurrency

    Returns:
        Tuple of (DataTableRow, failure_id or None)
    """
    async with semaphore:
        document_id = paper.id
        try:
            paper_col_values = await llm_client.extract_data_table(
                paper_content=paper.raw_content,
                columns=columns,
                document_id=document_id,
            )
            status_callback(f"extract for {paper.title} completed")
            return paper_col_values, None

        except Exception:
            logger.exception(
                "Failed to extract paper %s (%s)", document_id, paper.title
            )
            status_callback(f"extract for {paper.title} failed")

            # Return row with empty values to maintain paper ordering
            empty_row = DataTableRow(
                document_id=document_id,
                values={
                    col: DataTableCellValue(value="", citations=[]) for col in columns
                },
            )
            return empty_row, str(document_id)


async def construct_data_table(
    data_table_schema: DataTableSchema,
    status_callback: Callable[[str], None],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> DataTableResult:
    """
    Construct a data table based on the provided schema.

    Papers are processed concurrently in batches to improve performance.

    Args:
        data_table_schema: Schema defining the data table structure
        status_callback: Callback for status updates
        batch_size: Maximum number of papers to process concurrently (default: 5)

    Returns:
        The completed table, including row-level failure identifiers.
    """
    semaphore = asyncio.Semaphore(batch_size)

    # Create tasks for all papers
    tasks = [
        _process_single_paper(
            paper=p,
            columns=data_table_schema.columns,
            status_callback=status_callback,
            semaphore=semaphore,
        )
        for p in data_table_schema.papers
    ]

    # Process all papers concurrently (semaphore controls max parallelism)
    results = await asyncio.gather(*tasks)

    # Separate rows and failures while maintaining order
    rows: list[DataTableRow] = []
    row_failures: list[str] = []

    for row, failure_id in results:
        rows.append(row)
        if failure_id is not None:
            row_failures.append(failure_id)

    return DataTableResult(
        success=True,
        columns=list(data_table_schema.columns),
        rows=rows,
        row_failures=row_failures,
    )
