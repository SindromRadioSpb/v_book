"""Oracle for Hebrew term canonicalization (C06)."""

from __future__ import annotations

from app.domain.term_extraction.canonicalizer import (
    canonicalize_hebrew_term,
    choose_representative_term,
)

from tests.validation.oracles.base_oracle import OracleResult


def validate_canonicalization(case: dict) -> OracleResult:
    """Compare canonicalize_hebrew_term() output against gold.

    Args:
        case: A dict from c06_canonicalization.json canonicalize_cases[].
    """
    case_id = case["case_id"]
    surface = case["surface_text"]
    lemma = case.get("lemma_phrase")
    expected_canonical = case["expected_canonical"]

    actual_canonical = canonicalize_hebrew_term(surface, lemma)
    match = actual_canonical == expected_canonical

    return OracleResult(
        case_id=case_id,
        match=match,
        expected=expected_canonical,
        actual=actual_canonical,
        notes=case.get("notes", ""),
    )


def validate_representative_term(case: dict) -> OracleResult:
    """Compare choose_representative_term() output against gold.

    Args:
        case: A dict from c06_canonicalization.json representative_term_cases[].
    """
    case_id = case["case_id"]
    candidates = case["candidates"]
    expected_representative = case["expected_representative"]

    # choose_representative_term expects list of dicts with 'surface' and 'freq'
    actual_representative = choose_representative_term(candidates)
    match = actual_representative == expected_representative

    return OracleResult(
        case_id=case_id,
        match=match,
        expected=expected_representative,
        actual=actual_representative,
        notes=case.get("notes", ""),
    )
