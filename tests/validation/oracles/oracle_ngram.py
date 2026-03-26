"""Oracle for n-gram extraction validation (C04)."""

from __future__ import annotations

from app.domain.term_extraction.ngram_extractor import extract_ngrams_from_sentence

from tests.validation.oracles.base_oracle import OracleResult


def _ngram_key(ng: dict) -> tuple:
    """Stable comparison key: (surface_text, n, pos_pattern_tuple).

    Normalises pos_pattern to a tuple regardless of whether gold supplies
    a JSON array (list) or the extractor returns a pipe-joined string.
    """
    pos = ng["pos_pattern"]
    if isinstance(pos, list):
        pos = tuple(pos)
    elif isinstance(pos, str):
        pos = tuple(pos.split("|"))
    return (ng["surface_text"], ng["n"], pos)


def validate_ngram_extraction(case: dict) -> OracleResult:
    """Compare extract_ngrams_from_sentence() output against gold.

    Args:
        case: A dict from c04_ngram_extraction.json cases[].

    Returns:
        OracleResult with match=True iff actual key-set == expected key-set.
    """
    case_id = case["case_id"]
    tokens: list[dict] = case["input"]["tokens"]
    n_values: list[int] = case["input"].get("n_values", [2, 3])
    expected: list[dict] = case["expected_ngrams"]

    actual: list[dict] = extract_ngrams_from_sentence(tokens, n_values=n_values)

    expected_keys = {_ngram_key(ng) for ng in expected}
    actual_keys = {_ngram_key(ng) for ng in actual}

    match = expected_keys == actual_keys
    missing = [list(k) for k in (expected_keys - actual_keys)]
    extra = [list(k) for k in (actual_keys - expected_keys)]

    return OracleResult(
        case_id=case_id,
        match=match,
        expected=len(expected),
        actual=len(actual),
        missing=missing,
        extra=extra,
        notes=case.get("notes", ""),
    )
