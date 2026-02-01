"""PDF text extractor."""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_text(file_path: Path) -> str:
    """
    Extract text from PDF file (text-based PDFs only).

    For scanned PDFs, use pdf_ocr_extractor instead.
    Returns empty string if PyPDF2 is not available.
    """
    logger.info(f"Extracting text from PDF: {file_path}")

    try:
        from PyPDF2 import PdfReader
    except ImportError:
        logger.error("PyPDF2 not installed. Install with: pip install PyPDF2")
        raise ImportError("PyPDF2 library is required for PDF extraction")

    try:
        reader = PdfReader(file_path)
        pages_text = []

        for page_num, page in enumerate(reader.pages):
            try:
                text = page.extract_text()
                if text and text.strip():
                    pages_text.append(text.strip())
                    logger.debug(f"Extracted page {page_num + 1}: {len(text)} chars")
            except Exception as e:
                logger.warning(f"Failed to extract page {page_num + 1}: {e}")
                continue

        result = "\n\n".join(pages_text)

        if not result.strip():
            logger.warning(f"No text extracted from PDF (may be scanned). Try OCR extractor.")

        logger.info(f"Extracted {len(result)} characters from {len(pages_text)} pages")
        return result

    except Exception as e:
        logger.exception(f"Failed to extract text from PDF: {file_path}")
        raise RuntimeError(f"PDF extraction failed: {e}")
