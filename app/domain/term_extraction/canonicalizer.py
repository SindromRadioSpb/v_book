"""Hebrew term canonicalization for clustering (M5.1).

Handles normalization of Hebrew terms to merge surface variants:
- "בית ספר" (bare)
- "בבית ספר" (with prefix ב)
- "לבית הספר" (with prefix ל + article ה)
- "בית הספר" (with article ה)

All should map to same canonical key: "בית_ספר"
"""
import re
import logging
from typing import Optional

from app.domain.hebrew_utils import strip_nikud, strip_cantillation, normalize_whitespace

logger = logging.getLogger(__name__)

# Hebrew prefixes (single letters that attach to words)
HEBREW_PREFIXES = {
    'ב': 'in/at',
    'כ': 'like/as',
    'ל': 'to/for',
    'מ': 'from',
    'ו': 'and',
    'ש': 'that/which',
    'ה': 'the'  # article
}

# Hebrew quotes (gershayim/geresh)
GERSHAYIM = '\u05F4'  # ״
GERESH = '\u05F3'    # ׳


def normalize_quotes(text: str) -> str:
    """
    Normalize Hebrew quotation marks.

    Replaces gershayim (״) and geresh (׳) with standard ASCII equivalents.
    """
    text = text.replace(GERSHAYIM, '"')
    text = text.replace(GERESH, "'")
    return text


def strip_prefixes(word: str) -> str:
    """
    Remove common Hebrew prefixes from a word.

    Args:
        word: Hebrew word (single token)

    Returns:
        Word with prefixes stripped

    Examples:
        "בבית" → "בית" (if original is 4+ chars)
        "לבית" → "בית"
        "ובית" → "בית"
        "הבית" → "בית"
        "בית" → "בית" (unchanged - already base form)
    """
    if not word or len(word) < 2:
        return word

    # Strip prefixes iteratively (can have multiple: ו+ב+בית → בית)
    # But require at least 3 chars remaining to avoid over-stripping real words
    while len(word) >= 2 and word[0] in HEBREW_PREFIXES:
        # Only strip if we'll have at least 3 chars left
        if len(word) - 1 >= 3:
            word = word[1:]
        else:
            break

    return word


def canonicalize_hebrew_term(surface_text: str, lemma_phrase: Optional[str] = None) -> str:
    """
    Create canonical key for Hebrew term clustering.

    Process (in order):
    1. Strip nikud and cantillation
    2. Normalize quotes
    3. Normalize whitespace
    4. Strip prefixes from each token
    5. Join with underscores
    6. Lowercase (for case-insensitive clustering)

    If lemma_phrase is available, use it as primary key (already normalized).

    Args:
        surface_text: Surface form (e.g., "בבית ספר")
        lemma_phrase: Lemma form if available (e.g., "בית ספר")

    Returns:
        Canonical key (e.g., "בית_ספר")

    Examples:
        "בית ספר" → "בית_ספר"
        "בבית ספר" → "בית_ספר"
        "לבית הספר" → "בית_ספר"
        "בית הספר" → "בית_ספר"
    """
    # Prefer lemma_phrase if available (most normalized)
    if lemma_phrase:
        text = lemma_phrase
    else:
        text = surface_text

    # 1. Strip nikud and cantillation
    text = strip_nikud(text)
    text = strip_cantillation(text)

    # 2. Normalize quotes
    text = normalize_quotes(text)

    # 3. Normalize whitespace
    text = normalize_whitespace(text)

    # 4. Strip prefixes from each token
    tokens = text.split()
    tokens = [strip_prefixes(tok) for tok in tokens]

    # 5. Join with underscores (deterministic separator)
    canonical = '_'.join(tokens)

    # 6. Lowercase for case-insensitive clustering (Hebrew doesn't have case, but good practice)
    canonical = canonical.lower()

    # Remove any remaining special chars (punctuation)
    canonical = re.sub(r'[^\u0590-\u05FF_]', '', canonical)

    return canonical


def get_cluster_key(surface_text: str, lemma_phrase: Optional[str] = None) -> str:
    """
    Get cluster key for a term.

    This is the primary key used for clustering. Terms with the same cluster key
    will be grouped into one cluster.

    Args:
        surface_text: Surface form
        lemma_phrase: Lemma phrase (if available, preferred)

    Returns:
        Cluster key

    Examples:
        get_cluster_key("בית ספר", "בית ספר") → "בית_ספר"
        get_cluster_key("בבית ספר", "בית ספר") → "בית_ספר"
    """
    return canonicalize_hebrew_term(surface_text, lemma_phrase)


def choose_representative_term(terms: list[dict]) -> str:
    """
    Choose representative term from cluster members.

    Prefers:
    1. Highest frequency
    2. Shortest surface form (if frequencies equal)
    3. Alphabetically first (if still tied)

    Args:
        terms: List of dicts with 'surface_text' and 'freq_abs' keys

    Returns:
        Representative surface_text
    """
    if not terms:
        return ""

    # Sort by: freq desc, length asc, alphabetically
    sorted_terms = sorted(
        terms,
        key=lambda t: (-t.get('freq_abs', 0), len(t['surface_text']), t['surface_text'])
    )

    return sorted_terms[0]['surface_text']
