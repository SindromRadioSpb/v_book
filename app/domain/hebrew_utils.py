"""Hebrew text utilities (M3)."""
import re
import logging
from typing import List, Dict, Any

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


def merge_standalone_articles(tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge standalone Hebrew article/prefix tokens with following words.

    Handles Stanza tokenization artifacts where "התנועה" is tokenized as ["ה", "תנועה"].
    Merges "ה" + "תנועה" → "התנועה" for genuine article cases.

    Preserves standalone prefixes in legitimate contexts:
    - Enumerations: "סעיף ה." (section ה.) - prefix followed by punctuation
    - Variables: "ה = 5" (h = 5) - prefix followed by equals sign
    - Punctuation-separated: "ה:" "ה)" "ה," - prefix with trailing punctuation

    Args:
        tokens: List of token dicts with at least 'text' key (and optionally 'lemma', 'pos', etc.)

    Returns:
        Modified token list with merged tokens where appropriate

    Examples:
        >>> tokens = [{"text": "ה", "lemma": "ה", "pos": "DET"}, {"text": "ספר", "lemma": "ספר", "pos": "NOUN"}]
        >>> merge_standalone_articles(tokens)
        [{"text": "הספר", "lemma": "ספר", "pos": "NOUN"}]

        >>> tokens = [{"text": "סעיף"}, {"text": "ה"}, {"text": "."}]
        >>> merge_standalone_articles(tokens)
        [{"text": "סעיף"}, {"text": "ה"}, {"text": "."}]  # Unchanged - enumeration

        >>> tokens = [{"text": "ה"}, {"text": "="}]
        >>> merge_standalone_articles(tokens)
        [{"text": "ה"}, {"text": "="}]  # Unchanged - variable
    """
    # Import here to avoid circular dependency
    from app.domain.term_extraction.canonicalizer import HEBREW_PREFIXES

    if not tokens:
        return tokens

    merged = []
    skip_next = False

    for i, token in enumerate(tokens):
        if skip_next:
            skip_next = False
            continue

        token_text = token.get('text', '')

        # Check if current token is a standalone prefix (single Hebrew letter)
        if len(token_text) == 1 and token_text in HEBREW_PREFIXES:
            # Check if there's a next token to potentially merge with
            if i + 1 < len(tokens):
                next_token = tokens[i + 1]
                next_text = next_token.get('text', '')

                # Don't merge if next token is empty or starts with certain characters
                # Patterns to preserve:
                # - "ה." / "ה:" / "ה)" - enumerations
                # - "ה =" - variables/equations
                # - "ה," / "ה;" - punctuation separation
                if next_text and next_text[0] in '.,:;)]=':
                    # Keep separate - this is enumeration, variable, or intentional separation
                    merged.append(token)
                else:
                    # Merge: create new token with merged text
                    # Inherit properties from the base word (next_token), not the article
                    merged_token = next_token.copy()
                    merged_token['text'] = token_text + next_text
                    # Lemma stays as base word's lemma (article removed)
                    # POS stays as base word's POS (article is just a prefix)

                    merged.append(merged_token)
                    skip_next = True
            else:
                # No next token, keep as is (end of sentence)
                merged.append(token)
        else:
            # Not a standalone prefix, keep as is
            merged.append(token)

    return merged
