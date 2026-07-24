import io
import ipaddress
import logging
import socket
from datetime import datetime
from typing import Tuple
from urllib.parse import urljoin, urlsplit

import requests
from pypdf import PdfReader

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_UPLOAD_SIZE_MB = 30
DOCUMENT_PAGE_LIMIT = 800
MAX_URL_REDIRECTS = 5
URL_DOWNLOAD_TIMEOUT_SECONDS = 30
ALLOWED_PDF_CONTENT_TYPES = {
    "application/pdf",
    "application/octet-stream",
}


def get_start_page_from_offset(offsets: dict[int, Tuple[int, int]], offset: int) -> int:
    """
    Get the starting page number for a given text offset.
    """
    # Get last offset to ensure the offset is within bounds
    if not offsets:
        return -1  # Return -1 if no offsets are available
    last_page_num = max(offsets.keys())
    last_offset = offsets[last_page_num][1]
    if offset < 0 or offset >= last_offset:
        return -1  # Return -1 if the offset is out of bounds

    # Iterate through the offsets to find the page number for the given offset
    for page_num, (start, end) in offsets.items():
        if start <= offset < end:
            return page_num

    # Return -1 if no matching page is found. This condition should not occur if the offset is valid. Technically, the code should be unreachable given above checks, but need for completeness.
    return -1


def _detect_pdf_mime_type(pdf_bytes: bytes) -> bool:
    """
    Simple PDF detection without python-magic dependency.
    Returns True if the bytes appear to be a PDF.
    """
    # Check PDF header
    if not pdf_bytes.startswith(b"%PDF-"):
        return False

    # Additional basic checks for PDF structure
    # Look for common PDF markers
    pdf_markers = [b"%%EOF", b"/Type", b"/Catalog", b"xref"]

    # Convert to lowercase for case-insensitive search
    pdf_content = pdf_bytes.lower()

    # Check if at least 2 PDF markers are present
    marker_count = sum(1 for marker in pdf_markers if marker.lower() in pdf_content)

    return marker_count >= 2


async def validate_pdf_content(
    pdf_bytes: bytes, source: str = "upload"
) -> tuple[bool, str]:
    """
    Perform lightweight validation on PDF content.
    Returns (is_valid, error_message).
    """
    try:
        # Check file size
        if len(pdf_bytes) > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            return False, f"File too large (max {MAX_UPLOAD_SIZE_MB}MB)"

        # Check minimum file size (at least 1KB)
        if len(pdf_bytes) < 1024:
            return False, "File too small to be a valid PDF"

        # Verify it's a PDF using simple detection
        if not _detect_pdf_mime_type(pdf_bytes):
            return False, "File does not appear to be a valid PDF"

        # Try to read PDF structure
        pdf_stream = io.BytesIO(pdf_bytes)
        try:
            reader = PdfReader(pdf_stream)

            # Check if PDF has pages
            if len(reader.pages) == 0:
                return False, "PDF contains no pages"

            # Guard against extremely long PDFs that may exceed LLM context limits
            if len(reader.pages) > DOCUMENT_PAGE_LIMIT:
                return False, f"PDF exceeds the {DOCUMENT_PAGE_LIMIT}-page limit"

            # Check if PDF is encrypted and can't be processed
            if reader.is_encrypted:
                return False, "Encrypted PDFs are not supported"

            # Try to extract text from first page to verify it's readable
            first_page = reader.pages[0]
            text = first_page.extract_text()

            # Check if we can extract any text (even if minimal)
            # Some PDFs might be image-only but still valid
            if len(text.strip()) < 10:
                logger.warning(
                    f"PDF from {source} has minimal text content - might be image-only"
                )
                return False, "PDF appears to have minimal text content"

        except Exception:
            logger.info("Rejected unreadable PDF from %s", source, exc_info=True)
            return False, "PDF structure is corrupted or unreadable"

        return True, ""

    except Exception:
        logger.exception("Error validating PDF from %s", source)
        return False, "Failed to validate PDF"


def _validate_public_http_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only HTTP(S) PDF URLs are supported")
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Invalid PDF URL")

    try:
        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("PDF URL host could not be resolved") from exc

    if not addresses:
        raise ValueError("PDF URL host could not be resolved")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("PDF URL must resolve only to public addresses")


def _validate_public_response_peer(response: requests.Response) -> None:
    connection = getattr(response.raw, "_connection", None)
    socket_object = getattr(connection, "sock", None)
    if socket_object is None:
        response.close()
        raise ValueError("Could not verify PDF server address")
    peer_ip = ipaddress.ip_address(socket_object.getpeername()[0])
    if not peer_ip.is_global:
        response.close()
        raise ValueError("PDF server connection used a non-public address")


async def validate_url_and_fetch_pdf(url: str) -> tuple[bool, bytes, str]:
    """
    Validate URL and fetch PDF content with additional checks.
    Returns (is_valid, pdf_bytes, error_message).
    """
    try:
        max_bytes = MAX_UPLOAD_SIZE_MB * 1024 * 1024
        current_url = url
        session = requests.Session()
        session.trust_env = False
        response: requests.Response | None = None

        for redirect_count in range(MAX_URL_REDIRECTS + 1):
            _validate_public_http_url(current_url)
            response = session.get(
                current_url,
                timeout=URL_DOWNLOAD_TIMEOUT_SECONDS,
                stream=True,
                allow_redirects=False,
                headers={"Accept": "application/pdf"},
            )
            _validate_public_response_peer(response)
            if response.is_redirect or response.is_permanent_redirect:
                response.close()
                location = response.headers.get("location")
                if not location or redirect_count == MAX_URL_REDIRECTS:
                    return False, b"", "PDF URL has too many redirects"
                current_url = urljoin(current_url, location)
                continue
            break

        if response is None:
            return False, b"", "PDF download failed"
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type not in ALLOWED_PDF_CONTENT_TYPES:
            response.close()
            return False, b"", "URL did not return a PDF content type"

        content_length = response.headers.get("content-length")
        if content_length:
            if not content_length.isdigit():
                response.close()
                return False, b"", "PDF server returned an invalid content length"
            declared_size = int(content_length)
            if declared_size > max_bytes:
                response.close()
                return False, b"", f"File too large (max {MAX_UPLOAD_SIZE_MB}MB)"
            if declared_size < 1024:
                response.close()
                return False, b"", "File too small to be a valid PDF"

        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                response.close()
                return False, b"", f"File too large (max {MAX_UPLOAD_SIZE_MB}MB)"
            chunks.append(chunk)
        response.close()
        pdf_bytes = b"".join(chunks)

        # Validate the downloaded content
        is_valid, error_msg = await validate_pdf_content(pdf_bytes, "URL")
        if not is_valid:
            return False, b"", error_msg

        return True, pdf_bytes, ""

    except ValueError as exc:
        return False, b"", str(exc)
    except requests.exceptions.RequestException:
        logger.info("PDF URL download failed", exc_info=True)
        return False, b"", "Failed to download PDF from URL"
    except Exception:
        logger.exception("Unexpected PDF URL processing failure")
        return False, b"", "Failed to process PDF URL"


def extract_pdf_page_dimensions(pdf_bytes: bytes) -> dict[int, tuple[float, float]]:
    """
    Return {page_index: (width_pts, height_pts)} for every page in the PDF.

    Used to convert Zotero annotation positions (which are in PDF points) into the
    viewer's coordinate space. Preview/text generation lives in the jobs service;
    this only needs page geometry, which pypdf reads from the page cropbox.
    """
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        dims: dict[int, tuple[float, float]] = {}
        for i, page in enumerate(reader.pages):
            box = page.cropbox
            dims[i] = (float(box.width), float(box.height))
        return dims
    except Exception as e:
        logger.warning("Failed to extract PDF page dimensions: %s", e)
        return {}


def parse_publication_date(date_str: str) -> datetime | None:
    """Parse publication date string in various formats (yyyy-mm-dd, yyyy-mm, yyyy)."""
    if not date_str:
        return None

    formats = ["%Y-%m-%d", "%Y-%m", "%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None
