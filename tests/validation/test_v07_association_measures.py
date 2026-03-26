"""V07 — Association measures validation (C07).

Tests compute_pmi/llr/dice/tscore against hand-calculated expected values.
No Stanza required.
"""

from __future__ import annotations

import pytest

from tests.validation.oracles.oracle_measures import validate_association_measures


@pytest.fixture
def cases(gold_data):
    return gold_data("c07_association_measures")["cases"]


class TestAssociationMeasures:
    def test_all_cases_pass(self, cases):
        failures = []
        for case in cases:
            result = validate_association_measures(case)
            if not result.match:
                failures.append(
                    {
                        "case_id": result.case_id,
                        "expected": result.expected,
                        "actual": result.actual,
                        "details": result.missing,
                    }
                )
        assert not failures, f"Association measure failures:\n{failures}"

    def test_zero_c_xy_returns_all_none(self, cases):
        """C07_03: zero c_xy → PMI/tscore=None; dice=0.0; LLR from contingency table."""
        c = next(c for c in cases if c["case_id"] == "C07_03")
        result = validate_association_measures(c)
        assert result.match, f"Zero c_xy test failed: {result.missing}"
        assert result.actual["pmi"] is None
        assert result.actual["dice"] == 0.0, f"Expected dice=0.0, got {result.actual['dice']}"
        assert result.actual["llr"] is not None, "LLR should be non-None when c_xy=0"

    def test_dice_max_when_always_co_occur(self, cases):
        """C07_02: Dice must equal 1.0 when c_xy == c_x == c_y."""
        c = next(c for c in cases if c["case_id"] == "C07_02")
        result = validate_association_measures(c)
        assert (
            abs(result.actual["dice"] - 1.0) < 0.001
        ), f"Expected Dice=1.0, got {result.actual['dice']}"

    def test_pmi_negative_for_weak_association(self, cases):
        """C07_05: PMI must be negative when observed < expected (near-independence)."""
        c = next(c for c in cases if c["case_id"] == "C07_05")
        result = validate_association_measures(c)
        assert result.actual["pmi"] is not None
        assert result.actual["pmi"] < 0, f"Expected negative PMI, got {result.actual['pmi']}"

    def test_zero_n_returns_all_none(self, cases):
        """C07_06: n=0 — PMI/LLR/tscore=None; Dice is n-independent (returns 0.5)."""
        c = next(c for c in cases if c["case_id"] == "C07_06")
        result = validate_association_measures(c)
        assert result.actual["pmi"] is None
        assert (
            result.actual["dice"] == 0.5
        ), f"Dice does not depend on n; expected 0.5, got {result.actual['dice']}"

    def test_determinism(self):
        """Same inputs must produce same outputs on two calls."""
        from app.domain.term_extraction.association_measures import compute_pmi

        v1 = compute_pmi(10, 50, 40, 1000)
        v2 = compute_pmi(10, 50, 40, 1000)
        assert v1 == v2, "compute_pmi is non-deterministic"
