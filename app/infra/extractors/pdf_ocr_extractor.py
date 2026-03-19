"""PDF OCR extractor (Premium feature)."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def is_ocr_available() -> bool:
    """Check if OCR dependencies are available."""
    try:
        import pdf2image
        import pytesseract

        return True
    except ImportError:
        return False


def extract_text(file_path: Path) -> str:
    """
    Extract text from scanned PDF using OCR.

    Requires:
    - pytesseract
    - pdf2image
    - Tesseract binary (system dependency)

    Raises:
    - NotImplementedError if OCR dependencies are not available
    - RuntimeError if OCR extraction fails
    """
    logger.info(f"Extracting text from PDF with OCR: {file_path}")

    # Check dependencies
    if not is_ocr_available():
        error_msg = (
            "OCR dependencies not available. Install with:\n"
            "  pip install pytesseract pdf2image\n"
            "Also install Tesseract-OCR system binary:\n"
            "  Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
            "  Linux: sudo apt-get install tesseract-ocr\n"
            "  macOS: brew install tesseract"
        )
        logger.error(error_msg)
        raise NotImplementedError(error_msg)

    try:
        import pytesseract
        from pdf2image import convert_from_path

        # Convert PDF to images
        logger.info("Converting PDF pages to images...")
        images = convert_from_path(file_path)

        pages_text = []
        for page_num, image in enumerate(images):
            logger.info(f"OCR processing page {page_num + 1}...")
            # Perform OCR with Hebrew language support
            text = pytesseract.image_to_string(image, lang="heb+eng")
            if text and text.strip():
                pages_text.append(text.strip())

        result = "\n\n".join(pages_text)
        logger.info(f"OCR extracted {len(result)} characters from {len(pages_text)} pages")
        return result

    except Exception as e:
        logger.exception(f"Failed to extract text from PDF with OCR: {file_path}")
        raise RuntimeError(f"PDF OCR extraction failed: {e}")
