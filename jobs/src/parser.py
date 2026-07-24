"""Deterministic PDF preview generation.

Body parsing is intentionally handled only by MinerU.
"""

from __future__ import annotations

import logging
import uuid
from io import BytesIO

import pymupdf  # type: ignore
from PIL import Image  # type: ignore

from src.s3_service import s3_service

logger = logging.getLogger(__name__)


def generate_pdf_preview(file_path: str) -> tuple[str, str]:
    try:
        document = pymupdf.open(file_path)
        if len(document) == 0:
            raise ValueError("PDF has no pages")

        pixmap = document[0].get_pixmap(matrix=pymupdf.Matrix(2.0, 2.0))
        image: Image.Image = Image.open(BytesIO(pixmap.tobytes("png")))
        if image.width > 800:
            ratio = 800 / image.width
            image = image.resize(
                (800, int(image.height * ratio)),
                Image.Resampling.LANCZOS,
            )

        output = BytesIO()
        image.save(output, format="PNG", optimize=True)
        document.close()
        return s3_service.upload_any_file_from_bytes(
            output.getvalue(),
            f"preview-{uuid.uuid4()}.png",
            content_type="image/png",
        )
    except Exception:
        logger.error("Failed to generate PDF preview", exc_info=True)
        raise
