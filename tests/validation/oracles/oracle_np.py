"""Oracle for NP chunk extraction validation (C05)."""

from __future__ import annotations

from app.domain.term_extraction.np_extractor import extract_np_chunks_from_sentence

from tests.validation.oracles.base_oracle import OracleResult


def _chunk_key(chunk: dict) -> tuple:
    return (chunk["surface_text"], chunk["length"])


def validate_np_extraction(case: dict) -> OracleResult:
    """Compare extract_np_chunks_from_sentence() output against gold.

    Supports two gold formats:
    - expected_chunks: exact set match
    - expected_chunks_contain: subset match (all listed chunks must be present)
    """
    case_id = case["case_id"]
    tokens: list[dict] = case["input"]["tokens"]
    min_len: int = case["input"].get("min_len", 2)
    max_len: int = case["input"].get("max_len", 5)

    actual_raw: list[dict] = extract_np_chunks_from_sentence(
        tokens, min_len=min_len, max_len=max_len
    )

    # Normalise actual to surface_text + length dicts.
    # NP extractor uses "n" for span length; fall back to "length" then token_indices.
    actual = [
        {
            "surface_text": c.get("surface_text", ""),
            "length": c.get("n", c.get("length", len(c.get("token_indices", [])))),
        }
        for c in actual_raw
    ]
    actual_keys = {_chunk_key(c) for c in actual}

    if "expected_chunks" in case:
        expected = case["expected_chunks"]
        expected_keys = {_chunk_key(c) for c in expected}
        match = expected_keys == actual_keys
        missing = [list(k) for k in (expected_keys - actual_keys)]
        extra = [list(k) for k in (actual_keys - expected_keys)]
    elif "expected_chunks_contain" in case:
        # Subset match: all listed expected must appear in actual
        required_keys = {_chunk_key(c) for c in case["expected_chunks_contain"]}
        missing = [list(k) for k in (required_keys - actual_keys)]
        match = len(missing) == 0
        extra = []
        # Also check min_count if specified
        if "expected_min_count" in case:
            if len(actual) < case["expected_min_count"]:
                match = False
                extra.append(f"actual_count={len(actual)} < min={case['expected_min_count']}")
    else:
        match = True
        missing = []
        extra = []

    return OracleResult(
        case_id=case_id,
        match=match,
        expected=case.get("expected_count", len(case.get("expected_chunks", []))),
        actual=len(actual),
        missing=missing,
        extra=extra,
        notes=case.get("notes", ""),
    )
