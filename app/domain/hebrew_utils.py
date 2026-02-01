"""Hebrew text utilities (M3)."""
import re
import logging

logger = logging.getLogger(__name__)

# Unicode ranges for Hebrew characters
HEBREW_LETTERS = r"[\u0590-\u05FF]"
NIKUD_RANGE = r"[\u0591-\u05C7]"
CANTILLATION_RANGE = r"[\u0591-\u05AF]"


def strip_nikud(text: str) -> str:
    """Remove nikud (vowel points) from Hebrew text."""
    return re.sub(NIKUD_RANGE, "", text)


def strip_cantillation(text: str) -> str:
    """Remove cantillation marks from Hebrew text."""
    return re.sub(CANTILLATION_RANGE, "", text)


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace."""
    return re.sub(r"\s+", " ", text).strip()


def is_hebrew_text(text: str) -> bool:
    """Check if text contains Hebrew characters."""
    return bool(re.search(HEBREW_LETTERS, text))
