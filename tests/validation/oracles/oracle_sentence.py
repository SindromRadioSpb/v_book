"""Oracle for SentenceSplitter validation (C01)."""

from __future__ import annotations

from app.domain.sentence_splitter import SentenceSplitter

from tests.validation.oracles.base_oracle import OracleResult

_splitter = SentenceSplitter()


def validate_sentence_splitting(case: dict) -> OracleResult:
    """Compare SentenceSplitter output against gold expected sentences.

    Args:
        case: A dict from c01_sentence_splitting.json cases[].

    Returns:
        OracleResult with match=True iff actual == expected (order-sensitive).
    """
    case_id = case["case_id"]
    input_text: str = case["input"]
    expected: list[str] = case["expected_sentences"]

    actual: list[str] = _splitter.split(input_text)

    match = actual == expected
    missing = [s for s in expected if s not in actual]
    extra = [s for s in actual if s not in expected]

    return OracleResult(
        case_id=case_id,
        match=match,
        expected=expected,
        actual=actual,
        missing=missing,
        extra=extra,
        notes=case.get("notes", ""),
    )
