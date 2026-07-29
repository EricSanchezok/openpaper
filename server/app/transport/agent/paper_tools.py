import uuid
from logging import getLogger
from time import time

from app.bootstrap.providers import (
    build_paper_content,
    build_paper_download,
    build_paper_ingestion,
    build_paper_search,
    build_pdf_url_source,
    build_project_document_visibility,
)
from app.bootstrap.settings import AppSettings
from app.modules.papers.application.contracts.search import (
    PaperSearchFilters,
    PaperSearchRequest,
    PaperSearchScope,
)
from app.modules.papers.application.search import SearchCursorCodec, SearchPapers
from app.shared.application import Actor
from sqlalchemy.orm import Session

logger = getLogger(__name__)


def _ensure_paper_in_scope(
    document_id: str, restrict_to_document_ids: list[str] | None
) -> None:
    """Hard-fence a per-paper tool call to the @-mention scope when one is set.

    The evidence loop already withholds out-of-scope papers from the model's
    available-papers list, but this is a defense-in-depth check so a tool can
    never operate on a paper outside the scoped set.
    """
    if (
        restrict_to_document_ids is not None
        and document_id not in restrict_to_document_ids
    ):
        raise ValueError("Paper is not in the scoped set for this conversation")


# --------------------------------------------------------------
# Function declarations for LLM tools related to file operations
# --------------------------------------------------------------

# NOTE: REMEMBER TO UPDATE THE EVIDENCE GATHERING SYSTEM PROMPT WHEN ADDING OR CHANGING FUNCTIONALITY FOR ANY OF THESE TOOLS

read_file_function = {
    "name": "read_file",
    "description": "Use this tool when you need to read the entire content of a single paper. It's best for when you need a complete overview of the paper's text. If you're looking for specific information, consider using 'search_file' first.",
    "parameters": {
        "type": "object",
        "properties": {
            "document_id": {
                "type": "string",
                "description": "The ID of the paper whose file content to read.",
            },
        },
        "required": ["document_id"],
    },
}

search_file_function = {
    "name": "search_file",
    "description": "Use this tool to find specific information within a single paper. You will use a regular expression for powerful searches. It returns the lines that match your query, along with their line numbers. This is useful for pinpointing exact details without reading the whole paper. Think carefully about how to dynamically search for the correct terms based on the user's question.",
    "parameters": {
        "type": "object",
        "properties": {
            "document_id": {
                "type": "string",
                "description": "The ID of the paper to search in.",
            },
            "query": {
                "type": "string",
                "description": "The regex pattern to search for in the file content.",
            },
        },
        "required": ["document_id", "query"],
    },
}

view_file_function = {
    "name": "view_file",
    "description": "Use this tool when you want to look at a specific part of a paper. You must specify a range of lines to view. This is helpful when you already have an idea of where the information is, for example, after using 'search_file' and getting a line number. It helps you see the context around a specific line or section. Use this to get a focused view of the content without being overwhelmed by the entire paper, especially to collect more details.",
    "parameters": {
        "type": "object",
        "properties": {
            "document_id": {
                "type": "string",
                "description": "The ID of the paper whose file content to view.",
            },
            "range_start": {
                "type": "integer",
                "description": "The starting line number (0-based index).",
            },
            "range_end": {
                "type": "integer",
                "description": "The ending line number (exclusive, 0-based index).",
            },
        },
        "required": ["document_id", "range_start", "range_end"],
    },
}

read_abstract_function = {
    "name": "read_abstract",
    "description": "Use this tool to get a quick summary of a paper. The abstract provides a concise overview of the paper's main points. It's a great starting point to understand what the paper is about before diving into the full text.",
    "parameters": {
        "type": "object",
        "properties": {
            "document_id": {
                "type": "string",
                "description": "The ID of the paper whose abstract to read.",
            },
        },
        "required": ["document_id"],
    },
}

search_all_files_function = {
    "name": "search_all_files",
    "description": "Search for a specific query across all available papers using full-text search. This is useful for broad, exploratory searches when you're not sure which paper contains the information you need. It returns a list of matching lines with their corresponding paper IDs and line numbers. Think carefully about how to dynamically search for the correct terms based on the user's question. If you already know which paper to search in, `search_file` is a more targeted and efficient option.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to find in the file content of all papers. Use the '|' (pipe) character to separate alternative search terms (OR logic). Each term separated by '|' can be a single word OR a multi-word phrase that will be searched exactly as written. Examples: 'machine learning|neural network|deep learning' searches for any of these three phrases. 'quantum computing|qubit' searches for either the phrase 'quantum computing' or the word 'qubit'. Multi-word phrases preserve spaces and are matched as complete phrases. Hyphens are automatically converted to spaces, so use spaces in multi-word terms (e.g., 'red team' not 'red-team').",
            },
        },
        "required": ["query"],
    },
}


def read_file(
    document_id: str,
    current_user: Actor,
    db: Session,
    project_id: str | None = None,
    restrict_to_document_ids: list[str] | None = None,
) -> str:
    """
    Read the content of a file associated with a paper.
    """
    _ensure_paper_in_scope(document_id, restrict_to_document_ids)
    paper = build_paper_content(db=db).read(
        actor=current_user,
        document_id=uuid.UUID(document_id),
        project_id=uuid.UUID(project_id) if project_id else None,
    )
    file_content = paper.raw_content
    if not file_content:
        raise ValueError("File content not found")

    return str(file_content)


def search_file(
    document_id: str,
    query: str,
    current_user: Actor,
    db: Session,
    project_id: str | None = None,
    restrict_to_document_ids: list[str] | None = None,
) -> list[str]:
    """
    Search for a specific query (as regex) in the file content of a paper.
    Returns matching lines with line numbers.
    """
    _ensure_paper_in_scope(document_id, restrict_to_document_ids)
    return build_paper_content(db=db).search_document(
        actor=current_user,
        document_id=uuid.UUID(document_id),
        query=query,
        project_id=uuid.UUID(project_id) if project_id else None,
    )


def search_all_files(
    query: str,
    current_user: Actor,
    db: Session,
    project_id: str | None = None,
    restrict_to_document_ids: list[str] | None = None,
) -> dict[str, list[str]]:
    """
    Search for a specific query in the file content of all papers using full-text search.
    Returns a list of matching lines with paper IDs and line numbers.

    When restrict_to_document_ids is provided (e.g. from @-mention scoping), the
    search space is hard-limited to those papers.
    """
    start_time = time()

    settings = AppSettings()
    search = SearchPapers(
        build_paper_search(backend=settings.paper_search_backend, db=db),
        SearchCursorCodec(settings.paper_search_cursor_secret),
        build_project_document_visibility(db=db),
    )
    response = search(
        actor=current_user,
        request=PaperSearchRequest(
            query=query.replace("|", " OR "),
            scope=(
                PaperSearchScope.PROJECTS
                if project_id is not None
                else PaperSearchScope.ALL
            ),
            filters=PaperSearchFilters(
                project_id=uuid.UUID(project_id) if project_id else None,
                document_ids=(
                    [uuid.UUID(item) for item in restrict_to_document_ids]
                    if restrict_to_document_ids is not None
                    else None
                ),
            ),
            limit=100,
        ),
    )

    end_time = time()
    elapsed_time = end_time - start_time
    logger.info(
        f"Database search for matching lines completed in {elapsed_time:.2f} seconds"
    )

    results: dict[str, list[str]] = {}

    for item in response.items:
        document_id = str(item.document_id)
        for snippet in item.snippets:
            line = snippet.start_line or 1
            results.setdefault(document_id, []).append(f"{line}: {snippet.text}")

    return results


def view_file(
    document_id: str,
    range_start: int,
    range_end: int,
    current_user: Actor,
    db: Session,
    project_id: str | None = None,
    restrict_to_document_ids: list[str] | None = None,
) -> str:
    """
    View a specific range of lines from the file content of a paper.
    """
    _ensure_paper_in_scope(document_id, restrict_to_document_ids)
    paper = build_paper_content(db=db).read(
        actor=current_user,
        document_id=uuid.UUID(document_id),
        project_id=uuid.UUID(project_id) if project_id else None,
    )
    file_content = paper.raw_content
    if not file_content:
        raise ValueError("File content not found")

    lines = file_content.splitlines()
    if range_start < 0 or range_end > len(lines) or range_start >= range_end:
        raise ValueError("Invalid range specified")

    all_lines = lines[range_start:range_end]
    total_chunk = "\n".join(all_lines)
    total_chunk = (
        f"File content from lines {range_start + 1} to {range_end}:\n\n{total_chunk}"
    )

    return total_chunk


def read_abstract(
    document_id: str,
    current_user: Actor,
    db: Session,
    project_id: str | None = None,
    restrict_to_document_ids: list[str] | None = None,
) -> str:
    """
    Read the abstract of a paper.
    """
    _ensure_paper_in_scope(document_id, restrict_to_document_ids)
    paper = build_paper_content(db=db).read(
        actor=current_user,
        document_id=uuid.UUID(document_id),
        project_id=uuid.UUID(project_id) if project_id else None,
    )
    abstract = paper.abstract
    if not abstract:
        return f"Abstract for {paper.title} not found"

    return f"Abstract:\n\n{abstract.strip()}\n\n"


def get_download_url(
    document_id: str,
    current_user: Actor,
    db: Session,
    project_id: str | None = None,
    restrict_to_document_ids: list[str] | None = None,
) -> dict[str, object]:
    """Agent adapter over the same authorized download use case as HTTP."""
    _ensure_paper_in_scope(document_id, restrict_to_document_ids)
    result = build_paper_download(db=db)(
        actor=current_user,
        document_id=uuid.UUID(document_id),
        project_id=uuid.UUID(project_id) if project_id else None,
    )
    return result.model_dump()


async def ingest_paper_from_url(
    url: str,
    current_user: Actor,
    db: Session,
    project_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    """Agent adapter over the same idempotent ingestion use case as HTTP."""
    result = await build_paper_ingestion(db=db).from_url(
        actor=current_user,
        url=url,
        source=build_pdf_url_source(),
        project_id=uuid.UUID(project_id) if project_id else None,
        idempotency_key=idempotency_key,
        ip_address="agent",
    )
    return result.model_dump()
