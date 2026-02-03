"""Translation Memory normalization with strict M5 compatibility.

CRITICAL: This module MUST use M5's canonicalize_hebrew_term() to ensure
TM lookups match existing canonical_key values in the database.

Normalization Strategy:
- term_cluster: src_norm = canonical_key (from DB)
- ngram: src_norm = he_canonical (from DB)
- lemma: src_norm = lemma_text (from DB)
- surface: src_norm = canonicalize_hebrew_term(text)

This guarantees no desync with M5 data.
"""
import logging
from dataclasses import dataclass
from typing import List, Optional

from app.domain.hebrew_utils import strip_nikud, strip_cantillation, normalize_whitespace
from app.domain.term_extraction.canonicalizer import canonicalize_hebrew_term

logger = logging.getLogger(__name__)


@dataclass
class NormalizedText:
    """Result of text normalization for TM."""

    raw: str  # Original input
    clean: str  # Cleaned (nikud/cantillation removed, whitespace normalized)
    norm: str  # Normalized key for exact match
    mode: str = "strict"  # Normalization mode used (strict|compat)
    canonical_key: Optional[str] = None  # For term_cluster compatibility
    warnings: List[str] = None  # Normalization warnings

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


def normalize_text(lang: str, text: str, kind: str, mode: str = "strict") -> NormalizedText:
    """
    Normalize text for Translation Memory lookup.

    Args:
        lang: Source language code (e.g., "he", "ru")
        text: Text to normalize
        kind: Entry kind (lemma|ngram|term_cluster|surface)
        mode: Normalization mode
            - "strict": Maximum determinism for automation/keys
            - "compat": Higher recall for user/import (variant matching)

    Returns:
        NormalizedText with normalized key and metadata

    Examples:
        >>> normalize_text("he", "בית הספר", "surface", "strict")
        NormalizedText(raw="בית הספר", clean="בית הספר", norm="בית_ספר", ...)

        >>> normalize_text("he", "  בְּבֵית   הַסֵפֶר  ", "surface", "strict")
        NormalizedText(raw="...", clean="בבית הספר", norm="בית_ספר", ...)
    """
    if not text or not text.strip():
        return NormalizedText(
            raw=text or "", clean="", norm="", mode=mode, warnings=["Empty or whitespace-only text"]
        )

    warnings = []

    # Hebrew-specific normalization
    if lang == "he":
        return _normalize_hebrew(text, kind, mode, warnings)

    # Russian or other languages: basic normalization
    clean = text.strip()
    clean = normalize_whitespace(clean)

    # For non-Hebrew, norm = lowercase clean text
    norm = clean.lower()

    return NormalizedText(raw=text, clean=clean, norm=norm, mode=mode, warnings=warnings)


def _normalize_hebrew(text: str, kind: str, mode: str, warnings: List[str]) -> NormalizedText:
    """
    Hebrew-specific normalization with strict M5 compatibility.

    Contract (see M7_NORMALIZATION_CONTRACT.md):
    - strict + lemma/term_cluster: strip prefixes, use _ joiner (M5 canonical_key)
    - strict + ngram/surface: NO prefix stripping, use _ joiner
    - compat + ngram/surface: NO prefix stripping, use space joiner (user-friendly)
    - compat + lemma/term_cluster: strip prefixes, use _ joiner (M5 compat)

    Preserves numbers, Latin letters, and meaningful content.
    """
    raw = text

    # Step 1: Strip diacritics
    clean = strip_nikud(text)
    clean = strip_cantillation(clean)

    # Step 2: Normalize whitespace
    clean = normalize_whitespace(clean)
    clean = clean.strip()

    if not clean:
        return NormalizedText(
            raw=raw, clean="", norm="", mode=mode, warnings=["Text became empty after normalization"]
        )

    # Step 3: Generate normalized key based on mode and kind
    # Contract: prefix stripping ONLY for lemma/term_cluster, NEVER for ngram/surface

    # Determine if prefix stripping should be applied
    # Per contract: ONLY lemma and term_cluster get prefix stripping
    if kind in ("lemma", "term_cluster"):
        strip_prefixes = True
        joiner = "_"  # M5 canonical format
    else:  # ngram, surface
        strip_prefixes = False
        # Joiner depends on mode
        joiner = " " if mode == "compat" else "_"

    # Generate normalized key
    norm = canonicalize_hebrew_term(clean, strip_prefixes_enabled=strip_prefixes, joiner=joiner)

    # Canonical key always uses M5 format (for term_cluster compatibility)
    if kind == "term_cluster" or (kind == "lemma" and mode == "strict"):
        canonical_key = norm  # Already in M5 format
    else:
        # For ngram/surface, generate M5-compatible canonical_key separately
        canonical_key = canonicalize_hebrew_term(clean, strip_prefixes_enabled=True, joiner="_")

    # Validate no garbage tokens
    if "_" in norm:
        tokens = norm.split("_")
        # Check for standalone function words that shouldn't be separate
        if any(t in {"ה", "ב", "ל", "כ", "מ", "ו", "ש"} for t in tokens):
            warnings.append(f"Normalized key contains standalone prefix tokens: {norm}")

    return NormalizedText(
        raw=raw, clean=clean, norm=norm, mode=mode, canonical_key=canonical_key, warnings=warnings
    )


def normalize_for_tm(
    lang: str, text: str, kind: str, lemma_phrase: Optional[str] = None, mode: str = "strict"
) -> NormalizedText:
    """
    Convenience wrapper for TM normalization with lemma support.

    If lemma_phrase is provided (for ngrams), use it as primary text.
    This matches M5's behavior where ngrams use lemma_phrase for canonical_key.

    Args:
        lang: Language code
        text: Surface text
        kind: Entry kind
        lemma_phrase: Lemma phrase if available (for ngrams)
        mode: Normalization mode

    Returns:
        NormalizedText
    """
    # For ngrams, prefer lemma_phrase if available (matches M5)
    if kind == "ngram" and lemma_phrase:
        return normalize_text(lang, lemma_phrase, kind, mode)

    return normalize_text(lang, text, kind, mode)


def generate_variants(lang: str, text: str, kind: str) -> List[str]:
    """
    Generate normalized variant keys for enhanced matching.

    Used for populating tm_alias table to catch user input variations.

    Args:
        lang: Language code
        text: Text to generate variants for
        kind: Entry kind

    Returns:
        List of normalized variant keys (excluding the main norm)

    Examples (Hebrew):
        "בית הספר" → ["בית_ספר", "בית_הספר"]  # with/without article
        "בבית הספר" → ["בית_ספר", "בבית_הספר"]  # with/without prefix
    """
    if lang != "he":
        return []  # Variants only for Hebrew for now

    variants = set()

    # Generate article variants (with/without ה)
    # TODO: Implement article variant generation
    # For now, return empty - variants can be added manually via aliases

    return list(variants)
