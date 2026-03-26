"""V06 — Hebrew term canonicalization validation (C06).

Tests canonicalize_hebrew_term() and choose_representative_term().
No Stanza required.
"""

from __future__ import annotations

import pytest

from tests.validation.oracles.oracle_canonicalization import (
    validate_canonicalization,
    validate_representative_term,
)


@pytest.fixture
def canon_cases(gold_data):
    return gold_data("c06_canonicalization")["canonicalize_cases"]


@pytest.fixture
def repr_cases(gold_data):
    return gold_data("c06_canonicalization")["representative_term_cases"]


class TestCanonicalization:
    def test_all_canonicalization_cases(self, canon_cases):
        failures = []
        for case in canon_cases:
            result = validate_canonicalization(case)
            if not result.match:
                failures.append(
                    {
                        "case_id": result.case_id,
                        "expected": result.expected,
                        "actual": result.actual,
                    }
                )
        assert not failures, f"Canonicalization failures:\n{failures}"

    @pytest.mark.parametrize("case_idx", range(9))
    def test_individual_canonical(self, canon_cases, case_idx):
        if case_idx >= len(canon_cases):
            pytest.skip(f"Case {case_idx} out of range")
        case = canon_cases[case_idx]
        result = validate_canonicalization(case)
        assert (
            result.match
        ), f"Case {result.case_id}: expected='{result.expected}', actual='{result.actual}'"

    def test_prefix_stripping_produces_same_key(self, canon_cases):
        """Cases C06_01 through C06_04 must all map to 'בית_ספר'."""
        same_key_ids = {"C06_01", "C06_02", "C06_03", "C06_04"}
        results = {
            c["case_id"]: validate_canonicalization(c)
            for c in canon_cases
            if c["case_id"] in same_key_ids
        }
        canonicals = {r.actual for r in results.values()}
        assert (
            len(canonicals) == 1
        ), f"Expected all prefix variants to map to same key, got: {canonicals}"

    def test_determinism_canonicalization(self, canon_cases):
        """Same surface/lemma input must produce same canonical on two calls."""
        from app.domain.term_extraction.canonicalizer import canonicalize_hebrew_term

        for case in canon_cases:
            c1 = canonicalize_hebrew_term(case["surface_text"], case.get("lemma_phrase"))
            c2 = canonicalize_hebrew_term(case["surface_text"], case.get("lemma_phrase"))
            assert c1 == c2, f"Non-deterministic canonicalization for '{case['surface_text']}'"


class TestRepresentativeTerm:
    def test_all_representative_cases(self, repr_cases):
        failures = []
        for case in repr_cases:
            result = validate_representative_term(case)
            if not result.match:
                failures.append(
                    {
                        "case_id": result.case_id,
                        "expected": result.expected,
                        "actual": result.actual,
                    }
                )
        assert not failures, f"Representative term failures:\n{failures}"

    def test_prefers_highest_freq_when_tie(self, repr_cases):
        """C06_R02: higher freq must win over lower freq."""
        c = next(c for c in repr_cases if c["case_id"] == "C06_R02")
        result = validate_representative_term(c)
        assert result.match, f"Expected '{result.expected}', got '{result.actual}'"

    def test_prefers_shortest_on_freq_tie(self, repr_cases):
        """C06_R03: shortest surface wins when freq is equal."""
        c = next(c for c in repr_cases if c["case_id"] == "C06_R03")
        result = validate_representative_term(c)
        assert result.match, f"Expected '{result.expected}', got '{result.actual}'"
