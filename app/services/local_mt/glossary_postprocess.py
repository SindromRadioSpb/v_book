"""Glossary postprocessing for local MT.

Applies user-approved translation memory terms to MT output.
This improves translation quality by replacing MT suggestions with
approved terminology where available.

Algorithm:
1. Query approved TM entries for language pair
2. Match source segments against TM entries (exact match on normalized text)
3. Replace target segments with approved translations
4. Return updated translations + metadata about applied terms

Example:
    Source: ["database system", "file manager"]
    MT Output: ["מערכת בסיס נתונים", "מנהל קבצים"]

    If TM has approved term:
    - "database system" → "מערכת נתוני בסיס"

    Result: ["מערכת נתוני בסיס", "מנהל קבצים"]
    Applied: [{"src": "database system", "tm_translation": "מערכת נתוני בסיס"}]
"""
import logging
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.infra.sa_models import TMEntry, TMAlias

logger = logging.getLogger(__name__)


# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class AppliedTerm:
    """Metadata about an applied TM term."""

    segment_index: int
    src_text: str
    src_norm: str
    tm_translation: str
    mt_translation: str
    tm_id: int
    kind: str
    confidence: Optional[float] = None


@dataclass
class PostprocessResult:
    """Result of glossary postprocessing."""

    translations: List[str]  # Updated translations
    applied_terms: List[AppliedTerm]  # Terms that were applied
    match_count: int  # Number of matches found


# ============================================================================
# Normalization
# ============================================================================


def normalize_text(text: str) -> str:
    """
    Normalize text for TM matching.

    This should match the normalization used when creating TM entries.

    Args:
        text: Input text

    Returns:
        Normalized text (lowercase, whitespace normalized)
    """
    # Lowercase
    normalized = text.lower()

    # Normalize whitespace (collapse multiple spaces)
    normalized = " ".join(normalized.split())

    return normalized


# ============================================================================
# TM Query
# ============================================================================


def query_approved_terms(
    session: Session,
    src_lang: str,
    tgt_lang: str,
    project_id: Optional[int] = None,
) -> Dict[str, TMEntry]:
    """
    Query approved TM entries for language pair.

    Args:
        session: Database session
        src_lang: Source language code (e.g., "eng_Latn")
        tgt_lang: Target language code (e.g., "heb_Hebr")
        project_id: Optional project ID (None = global TM)

    Returns:
        Dict mapping src_norm → TMEntry
    """
    # Build query for approved terms
    stmt = select(TMEntry).where(
        TMEntry.src_lang == src_lang,
        TMEntry.tgt_lang == tgt_lang,
        TMEntry.status == "approved",
    )

    # Filter by scope
    if project_id is None:
        # Global TM only
        stmt = stmt.where(TMEntry.project_id.is_(None))
    else:
        # Project TM + global TM
        stmt = stmt.where(
            (TMEntry.project_id == project_id) | (TMEntry.project_id.is_(None))
        )

    # Execute query
    entries = session.execute(stmt).scalars().all()

    # Build lookup dict: src_norm → TMEntry
    term_dict = {}
    for entry in entries:
        term_dict[entry.src_norm] = entry

    logger.debug(f"Loaded {len(term_dict)} approved terms for {src_lang}→{tgt_lang}")

    return term_dict


def query_aliases(
    session: Session,
    tm_ids: List[int],
) -> Dict[str, int]:
    """
    Query aliases for TM entries.

    Args:
        session: Database session
        tm_ids: List of TM IDs

    Returns:
        Dict mapping alias_norm → tm_id
    """
    if not tm_ids:
        return {}

    stmt = select(TMAlias).where(TMAlias.tm_id.in_(tm_ids))
    aliases = session.execute(stmt).scalars().all()

    # Build lookup dict: alias_norm → tm_id
    alias_dict = {}
    for alias in aliases:
        alias_dict[alias.alias_norm] = alias.tm_id

    logger.debug(f"Loaded {len(alias_dict)} aliases for {len(tm_ids)} terms")

    return alias_dict


# ============================================================================
# Postprocessing
# ============================================================================


def apply_glossary(
    session: Session,
    source_segments: List[str],
    target_segments: List[str],
    src_lang: str,
    tgt_lang: str,
    project_id: Optional[int] = None,
) -> PostprocessResult:
    """
    Apply glossary terms to MT output.

    Args:
        session: Database session
        source_segments: Source text segments
        target_segments: MT-translated segments
        src_lang: Source language code
        tgt_lang: Target language code
        project_id: Optional project ID

    Returns:
        PostprocessResult with updated translations and metadata
    """
    if len(source_segments) != len(target_segments):
        raise ValueError(
            f"Segment count mismatch: {len(source_segments)} source, {len(target_segments)} target"
        )

    # Query approved terms
    term_dict = query_approved_terms(session, src_lang, tgt_lang, project_id)

    if not term_dict:
        # No approved terms available
        return PostprocessResult(
            translations=target_segments.copy(),
            applied_terms=[],
            match_count=0,
        )

    # Query aliases
    tm_ids = [entry.tm_id for entry in term_dict.values()]
    alias_dict = query_aliases(session, tm_ids)

    # Build reverse lookup: tm_id → TMEntry
    tm_id_to_entry = {entry.tm_id: entry for entry in term_dict.values()}

    # Apply glossary
    updated_translations = []
    applied_terms = []

    for i, (src_seg, tgt_seg) in enumerate(zip(source_segments, target_segments)):
        # Normalize source segment
        src_norm = normalize_text(src_seg)

        # Check for exact match
        matched_entry = None

        # 1. Try direct match
        if src_norm in term_dict:
            matched_entry = term_dict[src_norm]

        # 2. Try alias match
        elif src_norm in alias_dict:
            tm_id = alias_dict[src_norm]
            matched_entry = tm_id_to_entry.get(tm_id)

        # Apply match if found
        if matched_entry:
            # Replace with approved translation
            updated_translations.append(matched_entry.translation)

            # Record applied term
            applied_terms.append(AppliedTerm(
                segment_index=i,
                src_text=src_seg,
                src_norm=src_norm,
                tm_translation=matched_entry.translation,
                mt_translation=tgt_seg,
                tm_id=matched_entry.tm_id,
                kind=matched_entry.kind,
                confidence=matched_entry.confidence,
            ))

            logger.debug(
                f"Applied TM term: '{src_seg}' → '{matched_entry.translation}' "
                f"(replaced MT: '{tgt_seg}')"
            )
        else:
            # No match, keep MT translation
            updated_translations.append(tgt_seg)

    return PostprocessResult(
        translations=updated_translations,
        applied_terms=applied_terms,
        match_count=len(applied_terms),
    )


# ============================================================================
# Convenience Functions
# ============================================================================


def apply_glossary_to_text(
    session: Session,
    source_text: str,
    target_text: str,
    src_lang: str,
    tgt_lang: str,
    project_id: Optional[int] = None,
) -> tuple[str, List[AppliedTerm]]:
    """
    Apply glossary to single text pair (convenience wrapper).

    Args:
        session: Database session
        source_text: Source text
        target_text: MT-translated text
        src_lang: Source language code
        tgt_lang: Target language code
        project_id: Optional project ID

    Returns:
        Tuple of (updated_translation, applied_terms)
    """
    result = apply_glossary(
        session,
        source_segments=[source_text],
        target_segments=[target_text],
        src_lang=src_lang,
        tgt_lang=tgt_lang,
        project_id=project_id,
    )

    return result.translations[0], result.applied_terms
