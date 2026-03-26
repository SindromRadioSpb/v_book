"""V04v2 — N-gram extraction edge cases: NOUN+ADJ+NOUN trigram, PUNCT boundary,
mixed Hebrew/Latin, and lemma_phrase divergence (C04v2).

Extends C04 with:
  - NOUN+ADJ+NOUN trigram positive case (in VALID_POS_PATTERNS but missing from Wave 1)
  - PUNCT token breaks the sliding window — no n-gram spans a comma boundary
  - Mixed Hebrew/Latin PROPN+PROPN bigram extracted correctly
  - lemma_phrase diverges from surface_text — validate_ngram_lemmas() secondary oracle
    catches silent lemma corruption that the set-key oracle cannot detect

No implementation changes — all gaps were gold/test coverage gaps.
No Stanza required.
"""

from __future__ import annotations

import pytest

from app.domain.term_extraction.ngram_extractor import (
    VALID_POS_PATTERNS,
    extract_ngrams_from_sentence,
)
from tests.validation.oracles.oracle_ngram import validate_ngram_extraction, validate_ngram_lemmas


@pytest.fixture
def cases(gold_data):
    return gold_data("c04v2_ngram_extraction")["cases"]


# ---------------------------------------------------------------------------
# NOUN+ADJ+NOUN trigram
# ---------------------------------------------------------------------------


class TestNounAdjNounTrigram:
    def test_valid_pos_patterns_contains_noun_adj_noun(self):
        """NOUN+ADJ+NOUN must be in VALID_POS_PATTERNS.

        Pins the pattern set contract. If removed, C04v2_01 trigram cases would
        silently stop being extracted without a test failure at the pattern level.
        """
        assert (
            "NOUN",
            "ADJ",
            "NOUN",
        ) in VALID_POS_PATTERNS, "VALID_POS_PATTERNS must contain (NOUN, ADJ, NOUN)"

    def test_noun_adj_noun_trigram_extracted(self, cases):
        """C04v2_01: NOUN+ADJ+NOUN trigram extracted — positive example missing from Wave 1."""
        c = next(c for c in cases if c["case_id"] == "C04v2_01")
        result = validate_ngram_extraction(c)
        assert result.match, (
            f"C04v2_01 NOUN+ADJ+NOUN trigram failed: "
            f"missing={result.missing}, extra={result.extra}"
        )

    def test_noun_adj_noun_subspan_bigrams_extracted(self, cases):
        """C04v2_01: 3-token NOUN+ADJ+NOUN sentence yields 2 bigrams + 1 trigram (3 total).

        Sliding window at n=2 produces NOUN+ADJ (positions 0-1) and ADJ+NOUN (positions 1-2).
        At n=3 it produces the NOUN+ADJ+NOUN trigram (positions 0-2).
        """
        c = next(c for c in cases if c["case_id"] == "C04v2_01")
        result = validate_ngram_extraction(c)
        assert result.actual == 3, (
            f"3-token NOUN+ADJ+NOUN sentence must yield 3 n-grams "
            f"(NOUN+ADJ + ADJ+NOUN bigrams + NOUN+ADJ+NOUN trigram). Got: {result.actual}"
        )


# ---------------------------------------------------------------------------
# PUNCT boundary
# ---------------------------------------------------------------------------


class TestPunctBoundary:
    def test_punct_breaks_ngram_window(self, cases):
        """C04v2_02: PUNCT between two NOUN groups produces only bigrams on each side."""
        c = next(c for c in cases if c["case_id"] == "C04v2_02")
        result = validate_ngram_extraction(c)
        assert result.match, (
            f"C04v2_02 PUNCT boundary failed: " f"missing={result.missing}, extra={result.extra}"
        )

    def test_no_ngram_surface_contains_punct_token(self, cases):
        """C04v2_02: no extracted n-gram surface text contains the comma token.

        Directly verifies that is_valid_pos_pattern() filters out all windows
        containing PUNCT — not just inferred from the count.
        """
        c = next(c for c in cases if c["case_id"] == "C04v2_02")
        tokens = c["input"]["tokens"]
        n_values = c["input"].get("n_values", [2, 3])
        actual = extract_ngrams_from_sentence(tokens, n_values=n_values)
        surfaces_with_punct = [ng["surface_text"] for ng in actual if "," in ng["surface_text"]]
        assert not surfaces_with_punct, (
            f"No n-gram surface must contain the PUNCT token ','. " f"Got: {surfaces_with_punct}"
        )


# ---------------------------------------------------------------------------
# Mixed Hebrew/Latin
# ---------------------------------------------------------------------------


class TestMixedScript:
    def test_mixed_script_propn_propn_extracted(self, cases):
        """C04v2_03: 'Apple ישראל' (PROPN+PROPN) bigram extracted — Latin token preserved."""
        c = next(c for c in cases if c["case_id"] == "C04v2_03")
        result = validate_ngram_extraction(c)
        assert result.match, (
            f"Mixed-script PROPN+PROPN bigram 'Apple ישראל' failed: "
            f"missing={result.missing}, extra={result.extra}"
        )


# ---------------------------------------------------------------------------
# Lemma divergence — secondary oracle
# ---------------------------------------------------------------------------


class TestLemmaDivergence:
    def test_lemma_phrase_diverges_from_surface(self, cases):
        """C04v2_04: 'עיתונים ישנים' surface; lemma 'עיתון ישן' — non-trivial divergence case."""
        c = next(c for c in cases if c["case_id"] == "C04v2_04")
        result = validate_ngram_extraction(c)
        assert result.match, (
            f"C04v2_04 lemma-divergence case failed set-key check: "
            f"missing={result.missing}, extra={result.extra}"
        )

    def test_validate_ngram_lemmas_passes_for_correct_output(self, cases):
        """C04v2_04: validate_ngram_lemmas() returns no mismatches when extractor is correct."""
        c = next(c for c in cases if c["case_id"] == "C04v2_04")
        tokens = c["input"]["tokens"]
        n_values = c["input"].get("n_values", [2, 3])
        actual = extract_ngrams_from_sentence(tokens, n_values=n_values)
        mismatches = validate_ngram_lemmas(c, actual)
        assert (
            not mismatches
        ), f"Expected no lemma mismatches for correct extractor output. Got: {mismatches}"

    def test_validate_ngram_lemmas_catches_corruption(self, cases):
        """validate_ngram_lemmas() detects when lemma_phrase is corrupted in actual output.

        Constructs a fake actual result where lemma_phrase equals surface_text (common
        regression — lemma field not populated). Verifies the secondary oracle has
        real detection power beyond the set-key check.
        """
        c = next(c for c in cases if c["case_id"] == "C04v2_04")
        corrupted_actual = [
            {
                "n": 2,
                "surface_text": "עיתונים ישנים",
                "lemma_phrase": "עיתונים ישנים",  # wrong — should be "עיתון ישן"
                "pos_pattern": "NOUN|ADJ",
                "token_ids": [0, 1],
            }
        ]
        mismatches = validate_ngram_lemmas(c, corrupted_actual)
        assert (
            len(mismatches) == 1
        ), f"Expected 1 mismatch for corrupted lemma_phrase. Got: {mismatches}"
        assert mismatches[0]["expected_lemma"] == "עיתון ישן"
        assert mismatches[0]["actual_lemma"] == "עיתונים ישנים"


# ---------------------------------------------------------------------------
# Full bulk pass
# ---------------------------------------------------------------------------


class TestAllC04v2Cases:
    def test_all_c04v2_cases_pass(self, cases):
        """All 4 C04v2 gold cases must pass the set-key oracle check."""
        failures = []
        for case in cases:
            result = validate_ngram_extraction(case)
            if not result.match:
                failures.append(
                    {
                        "case_id": result.case_id,
                        "missing": result.missing,
                        "extra": result.extra,
                    }
                )
        assert not failures, f"C04v2 n-gram extraction failures:\n{failures}"
