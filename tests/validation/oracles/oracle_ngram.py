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


def validate_ngram_lemmas(case: dict, actual: list[dict]) -> list[dict]:
    """Secondary check: verify lemma_phrase for gold cases where it diverges from surface.

    The main oracle key (surface_text, n, pos_tuple) cannot detect silent lemma
    corruption — if lemma_phrase is wrong but surface_text is correct the set key
    still matches. This function closes that gap.

    Args:
        case: Gold case dict (from c04v2_ngram_extraction.json or any C04 case).
        actual: Output of extract_ngrams_from_sentence().

    Returns:
        List of mismatch dicts (empty = all correct).
        Each entry: {"case_id", "surface_text", "expected_lemma", "actual_lemma"}
    """
    case_id = case["case_id"]
    mismatches = []
    for exp_ng in case.get("expected_ngrams", []):
        exp_lemma = exp_ng.get("lemma_phrase")
        exp_surface = exp_ng.get("surface_text")
        if not exp_lemma or exp_lemma == exp_surface:
            continue  # trivial case — no divergence to check
        exp_key = _ngram_key(exp_ng)
        actual_ng = next((a for a in actual if _ngram_key(a) == exp_key), None)
        if actual_ng is None:
            continue  # missing from actual — already caught by main oracle
        if actual_ng.get("lemma_phrase") != exp_lemma:
            mismatches.append(
                {
                    "case_id": case_id,
                    "surface_text": exp_surface,
                    "expected_lemma": exp_lemma,
                    "actual_lemma": actual_ng.get("lemma_phrase"),
                }
            )
    return mismatches
