"""V01 — Sentence splitting validation (C01).

Tests SentenceSplitter against gold expected sentences.
No Stanza required — pure rule-based splitter.
"""

from __future__ import annotations

import pytest

from tests.validation.oracles.oracle_sentence import validate_sentence_splitting


@pytest.fixture
def cases(gold_data):
    return gold_data("c01_sentence_splitting")["cases"]


class TestSentenceSplitting:
    def test_all_cases_pass(self, cases):
        """All C01 gold cases must pass."""
        failures = []
        for case in cases:
            result = validate_sentence_splitting(case)
            if not result.match:
                failures.append(
                    {
                        "case_id": result.case_id,
                        "expected": result.expected,
                        "actual": result.actual,
                        "missing": result.missing,
                        "extra": result.extra,
                    }
                )
        assert not failures, f"Sentence splitting failures:\n{failures}"

    @pytest.mark.parametrize("case_idx", range(8))
    def test_individual_case(self, cases, case_idx):
        """Each C01 case individually for precise failure attribution."""
        if case_idx >= len(cases):
            pytest.skip(f"Case index {case_idx} out of range ({len(cases)} cases)")
        case = cases[case_idx]
        result = validate_sentence_splitting(case)
        assert (
            result.match
        ), f"Case {result.case_id}: expected={result.expected}, actual={result.actual}"

    def test_expected_sentence_count(self, cases):
        """Actual sentence count must equal expected_count for all cases."""
        from app.domain.sentence_splitter import SentenceSplitter

        splitter = SentenceSplitter()
        for case in cases:
            actual = splitter.split(case["input"])
            assert len(actual) == case["expected_count"], (
                f"Case {case['case_id']}: expected {case['expected_count']} sentences, "
                f"got {len(actual)}: {actual}"
            )

    def test_determinism(self, cases):
        """Same input must produce same output across two runs."""
        from app.domain.sentence_splitter import SentenceSplitter

        splitter = SentenceSplitter()
        for case in cases:
            run1 = splitter.split(case["input"])
            run2 = splitter.split(case["input"])
            assert run1 == run2, f"Case {case['case_id']}: non-deterministic output"
