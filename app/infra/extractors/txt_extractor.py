"""Plain text extractor."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_text(file_path: Path) -> str:
    """
    Extract text from plain text file.

    Supports multiple encodings with fallback:
    1. UTF-8 (primary)
    2. UTF-8 with BOM
    3. Windows-1252 (common Windows encoding)
    4. ISO-8859-1 (Latin-1)
    """
    logger.info(f"Extracting text from TXT: {file_path}")

    encodings = ["utf-8", "utf-8-sig", "windows-1252", "iso-8859-1"]

    for encoding in encodings:
        try:
            text = file_path.read_text(encoding=encoding)
            logger.debug(f"Successfully read with encoding: {encoding}")
            return text
        except UnicodeDecodeError:
            logger.debug(f"Failed to decode with {encoding}, trying next")
            continue

    # If all fail, read as binary and replace errors
    logger.warning("All encodings failed, using UTF-8 with error replacement")
    return file_path.read_text(encoding="utf-8", errors="replace")
