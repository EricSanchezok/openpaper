"""PDF ingestion and parsing domain."""

from src.pdf.mineru import MinerUConfig
from src.pdf.state import parser_state_redis_url


def validate_pdf_runtime_configuration() -> None:
    """Fail fast for production-only parser requirements."""
    config = MinerUConfig.from_env()
    if config is not None:
        parser_state_redis_url()
