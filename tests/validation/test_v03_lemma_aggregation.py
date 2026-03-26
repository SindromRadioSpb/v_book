"""V03 — Lemma aggregation validation (C03).

Tests simulate_aggregation() and validate_lemma_aggregation() against gold
expected Freq/Docs values. No Stanza required — uses pre-tokenized inputs.
"""

from __future__ import annotations

import pytest

from tests.validation.oracles.oracle_lemma_agg import (
    simulate_aggregation,
    validate_lemma_aggregation,
)


@pytest.fixture
def case(gold_data):
    return gold_data("c03_lemma_aggregation")


class TestLemmaAggregation:
    def test_all_lemmas_present(self, case):
        """All expected lemmas must appear in the aggregated output."""
        result = validate_lemma_aggregation(case)
        assert result.match, f"Lemma aggregation failures:\n{result.missing}"

    def test_freq_yeled(self, case):
        """ילד: appears 3x in DOC_01 + 1x in DOC_02 = freq 4."""
        actual = {r["lemma"]: r for r in simulate_aggregation(case["documents"])}
        assert actual["ילד"]["freq"] == 4, f"Expected freq=4, got {actual['ילד']['freq']}"

    def test_docs_yeled(self, case):
        """ילד: appears in exactly 2 distinct documents."""
        actual = {r["lemma"]: r for r in simulate_aggregation(case["documents"])}
        assert actual["ילד"]["docs"] == 2, f"Expected docs=2, got {actual['ילד']['docs']}"

    def test_freq_gadol(self, case):
        """גדול: 1x in each of 3 docs = freq 3."""
        actual = {r["lemma"]: r for r in simulate_aggregation(case["documents"])}
        assert actual["גדול"]["freq"] == 3

    def test_docs_gadol(self, case):
        """גדול: appears in all 3 documents."""
        actual = {r["lemma"]: r for r in simulate_aggregation(case["documents"])}
        assert actual["גדול"]["docs"] == 3

    def test_freq_katan(self, case):
        """קטן: 1x in DOC_02 + 2x in DOC_03 = freq 3."""
        actual = {r["lemma"]: r for r in simulate_aggregation(case["documents"])}
        assert actual["קטן"]["freq"] == 3

    def test_docs_katan(self, case):
        """קטן: appears in 2 distinct documents (DOC_02, DOC_03)."""
        actual = {r["lemma"]: r for r in simulate_aggregation(case["documents"])}
        assert actual["קטן"]["docs"] == 2

    def test_hapax_lemmas(self, case):
        """בית and ספר each appear once in one document."""
        actual = {r["lemma"]: r for r in simulate_aggregation(case["documents"])}
        assert actual["בית"]["freq"] == 1 and actual["בית"]["docs"] == 1
        assert actual["ספר"]["freq"] == 1 and actual["ספר"]["docs"] == 1


class TestLemmaInvariants:
    def test_docs_never_exceeds_freq(self, case):
        """Invariant: docs <= freq for every lemma."""
        actual = simulate_aggregation(case["documents"])
        violations = [r for r in actual if r["docs"] > r["freq"]]
        assert not violations, f"docs > freq for: {violations}"

    def test_total_token_count(self, case):
        """Sum of all freq values == total token count across all docs (12)."""
        actual = simulate_aggregation(case["documents"])
        total = sum(r["freq"] for r in actual)
        assert total == 12, f"Expected total=12, got {total}"

    def test_no_duplicate_lemmas(self, case):
        """Each lemma appears exactly once in aggregate output."""
        actual = simulate_aggregation(case["documents"])
        lemmas = [r["lemma"] for r in actual]
        assert len(lemmas) == len(set(lemmas)), f"Duplicate lemmas: {lemmas}"

    def test_determinism(self, case):
        """Same document set must produce same aggregation on two calls."""
        r1 = simulate_aggregation(case["documents"])
        r2 = simulate_aggregation(case["documents"])
        assert sorted(r1, key=lambda x: x["lemma"]) == sorted(
            r2, key=lambda x: x["lemma"]
        ), "simulate_aggregation is non-deterministic"
