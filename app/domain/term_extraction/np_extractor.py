"""NP-chunk extraction from processed sentences (M5.3)."""

import logging

from app.domain.hebrew_utils import merge_standalone_articles

logger = logging.getLogger(__name__)

# Stop POS tags - these terminate NP candidates
STOP_POS = {
    "PUNCT",  # Punctuation
    "ADP",  # Adposition (prepositions)
    "CCONJ",  # Coordinating conjunction
    "SCONJ",  # Subordinating conjunction
    "PRON",  # Pronoun
    "VERB",  # Verb
    "AUX",  # Auxiliary
    "PART",  # Particle
}

# Core NP POS tags
CORE_NP_POS = {"NOUN", "PROPN"}

# Modifier POS tags
MODIFIER_POS = {"ADJ", "NUM"}

# DET allowed only as first token
DET_POS = {"DET"}


def is_valid_np_token(pos: str, is_first: bool = False) -> bool:
    """
    Check if POS tag is valid for NP composition.

    Args:
        pos: POS tag
        is_first: Whether this is the first token in the NP

    Returns:
        True if valid
    """
    if pos in CORE_NP_POS or pos in MODIFIER_POS:
        return True
    if is_first and pos in DET_POS:
        return True
    return False


def extract_np_chunks_from_sentence(
    tokens: list[dict], min_len: int = 2, max_len: int = 5
) -> list[dict]:
    """
    Extract noun phrase chunks from a single sentence.

    Rules:
    - Split at PUNCT and stop POS
    - Allow: (DET)? (ADJ|NUM)* (NOUN|PROPN)+ (ADJ|NUM)*
    - Length: min_len <= n <= max_len tokens
    - Must contain at least one CORE_NP_POS (NOUN or PROPN)

    Args:
        tokens: List of token dicts with keys: text, lemma, pos
        min_len: Minimum NP length (default 2)
        max_len: Maximum NP length (default 5)

    Returns:
        List of NP chunk dicts with keys:
        - n: chunk length
        - surface_text: surface form
        - lemma_phrase: lemma form
        - pos_pattern: pipe-separated POS tags
        - token_ids: indices in sentence
    """
    if not tokens or max_len < min_len:
        return []

    np_chunks = []

    # Split sentence into segments at boundaries (PUNCT, stop POS)
    segments = []
    current_segment = []
    current_start_idx = 0

    for idx, token in enumerate(tokens):
        if token["pos"] in STOP_POS:
            # Save current segment if not empty
            if current_segment:
                segments.append((current_segment, current_start_idx))
                current_segment = []
            current_start_idx = idx + 1
        else:
            current_segment.append((token, idx))

    # Add last segment
    if current_segment:
        segments.append((current_segment, current_start_idx))

    # Extract NP candidates from each segment
    for segment, segment_start in segments:
        if len(segment) < min_len:
            continue

        # Scan all possible spans within this segment
        for start in range(len(segment)):
            for length in range(min_len, min(max_len, len(segment) - start) + 1):
                end = start + length
                span = segment[start:end]

                # Extract tokens and POS
                span_tokens = [t[0] for t in span]
                pos_tags = [t["pos"] for t in span_tokens]
                token_indices = [t[1] for t in span]

                # Validate NP composition
                if not _is_valid_np_span(pos_tags):
                    continue

                # Merge standalone articles (e.g., "ה" + "ספר" → "הספר")
                # Fixes tokenization artifacts where definite article is separated
                span_tokens = merge_standalone_articles(span_tokens)

                # Build surface and lemma forms
                surface_tokens = [tok["text"] for tok in span_tokens]
                lemma_tokens = [tok["lemma"] for tok in span_tokens]

                surface_text = " ".join(surface_tokens)
                lemma_phrase = " ".join(lemma_tokens)
                pos_pattern = "|".join(pos_tags)

                np_chunks.append(
                    {
                        "n": length,
                        "surface_text": surface_text,
                        "lemma_phrase": lemma_phrase,
                        "pos_pattern": pos_pattern,
                        "token_ids": token_indices,
                    }
                )

    return np_chunks


def _is_valid_np_span(pos_tags: list[str]) -> bool:
    """
    Validate NP span according to composition rules.

    Rules:
    - Must contain at least one CORE_NP_POS (NOUN or PROPN)
    - DET allowed only as first token
    - All other tokens must be CORE_NP_POS or MODIFIER_POS
    - No stop POS inside span (already filtered by segmentation)

    Args:
        pos_tags: List of POS tags in span

    Returns:
        True if valid NP span
    """
    if not pos_tags:
        return False

    # Must have at least one core NP tag (NOUN or PROPN)
    has_core = any(pos in CORE_NP_POS for pos in pos_tags)
    if not has_core:
        return False

    # Check first token
    first_pos = pos_tags[0]
    if not is_valid_np_token(first_pos, is_first=True):
        return False

    # Check remaining tokens (DET not allowed)
    for pos in pos_tags[1:]:
        if pos not in CORE_NP_POS and pos not in MODIFIER_POS:
            return False

    return True
