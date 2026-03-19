"""Text preprocessing pipeline (M3)."""

import logging

from app.domain.hebrew_utils import normalize_whitespace, strip_cantillation, strip_nikud

logger = logging.getLogger(__name__)


def preprocess_text(text: str) -> str:
    """
    Preprocess Hebrew text:
    - Strip nikud and cantillation
    - Normalize quotes
    - Normalize whitespace
    """
    if not text:
        return ""

    # Strip nikud and cantillation
    text = strip_nikud(text)
    text = strip_cantillation(text)

    # Normalize quotes
    text = text.replace("\u201c", '"').replace("\u201d", '"')  # Smart quotes
    text = text.replace("\u2018", "'").replace("\u2019", "'")  # Smart single quotes
    text = text.replace("\u05f4", '"')  # Hebrew gershayim
    text = text.replace("\u05f3", "'")  # Hebrew geresh

    # Normalize whitespace
    text = normalize_whitespace(text)

    return text
