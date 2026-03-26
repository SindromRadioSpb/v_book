"""V04 — N-gram extraction validation (C04).

Tests extract_ngrams_from_sentence() against gold expected n-grams.
No Stanza required — uses pre-tokenized inputs.
"""

from __future__ import annotations

import pytest

from tests.validation.oracles.oracle_ngram import validate_ngram_extraction


@pytest.fixture
def cases(gold_data):
    return gold_data("c04_ngram_extraction")["cases"]


class TestNgramExtraction:
    def test_all_cases_pass(self, cases):
        """All C04 gold cases must pass."""
        failures = []
        for case in cases:
            result = validate_ngram_extraction(case)
            if not result.match:
                failures.append(
                    {
                        "case_id": result.case_id,
                        "expected_count": result.expected,
                        "actual_count": result.actual,
                        "missing": result.missing,
                        "extra": result.extra,
                    }
                )
        assert not failures, f"N-gram extraction failures:\n{failures}"

    @pytest.mark.parametrize("case_idx", range(9))
    def test_individual_case(self, cases, case_idx):
        if case_idx >= len(cases):
            pytest.skip(f"Case index {case_idx} out of range")
        case = cases[case_idx]
        result = validate_ngram_extraction(case)
        assert (
            result.match
        ), f"Case {result.case_id}: missing={result.missing}, extra={result.extra}"

    def test_invalid_pos_pattern_produces_no_ngrams(self, cases):
        """C04_07: VERB+NOUN pattern must produce zero n-grams."""
        c = next(c for c in cases if c["case_id"] == "C04_07")
        result = validate_ngram_extraction(c)
        assert result.actual == 0, f"Expected 0 n-grams, got {result.actual}"

    def test_single_token_produces_no_ngrams(self, cases):
        """C04_08: single token cannot form a bigram or trigram."""
        c = next(c for c in cases if c["case_id"] == "C04_08")
        result = validate_ngram_extraction(c)
        assert result.actual == 0, f"Expected 0 n-grams for single token, got {result.actual}"

    def test_trigram_sliding_window(self, cases):
        """C04_06: 3-token NOUN+NOUN+NOUN sentence yields both bigrams and the trigram."""
        c = next(c for c in cases if c["case_id"] == "C04_06")
        result = validate_ngram_extraction(c)
        assert (
            result.match
        ), f"Sliding window test failed: missing={result.missing}, extra={result.extra}"

    def test_determinism(self):
        """Same token input must produce same n-gram set across two calls."""
        from app.domain.term_extraction.ngram_extractor import extract_ngrams_from_sentence

        tokens = [
            {"text": "בית", "lemma": "בית", "pos": "NOUN"},
            {"text": "ספר", "lemma": "ספר", "pos": "NOUN"},
            {"text": "גדול", "lemma": "גדול", "pos": "ADJ"},
        ]
        run1 = extract_ngrams_from_sentence(tokens)
        run2 = extract_ngrams_from_sentence(tokens)
        assert run1 == run2, "N-gram extraction is non-deterministic"
