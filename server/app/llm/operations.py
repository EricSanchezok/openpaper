from app.llm.citation_handler import CitationHandler
from app.llm.conversation_operations import ConversationOperations, DataTableOperations
from app.llm.json_parser import JSONParser
from app.llm.multi_paper_operations import MultiPaperOperations
from app.llm.paper_operations import PaperOperations


class Operations(
    PaperOperations,
    MultiPaperOperations,
    ConversationOperations,
    DataTableOperations,
):
    """
    Unified operations class that combines all LLM operations
    """

    pass


__all__ = [
    "Operations",
    "PaperOperations",
    "MultiPaperOperations",
    "ConversationOperations",
    "CitationHandler",
    "JSONParser",
    "DataTableOperations",
]

operations = Operations()
