"""V03v2 — Lemma aggregation edge cases: hapax, all-doc lemma, empty document,
multi-frequency stress, all-empty corpus (C03v2).

Extends C03 with 5 new scenarios covering edge cases not exercised by the
single 3-doc corpus in C03 Wave 1:
  - C03v2_HAPAX: single-doc single-occurrence lemma in isolation
  - C03v2_ALLDOC: all-doc lemma with non-uniform per-doc frequency
  - C03v2_EMPTYDOC: corpus with one empty document (empty doc = 0 contribution)
  - C03v2_STRESS: high-freq/low-docs vs all-doc vs hapax in one corpus
  - C03v2_ALLEMPTY: all documents empty → no aggregates produced

Invariants (docs ≤ freq, no duplicates, total_tokens_match) are now enforced
across all 5 scenarios via parametrize, not just the C03 baseline scenario.

Oracle note: simulate_aggregation() is pure Python and does not call the actual
DB-level aggregation service. DB-level correctness belongs to a separate
integration test layer. This is explicitly by design.

No implementation changes. No Stanza required.
"""

from __future__ import annotations

import pytest

from tests.validation.oracles.oracle_lemma_agg import (
    simulate_aggregation,
    validate_lemma_aggregation,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SCENARIO_IDS = [
    "C03v2_HAPAX",
    "C03v2_ALLDOC",
    "C03v2_EMPTYDOC",
    "C03v2_STRESS",
    "C03v2_ALLEMPTY",
]


@pytest.fixture
def scenarios(gold_data):
    """All C03v2 scenarios as a dict keyed by corpus_id."""
    raw = gold_data("c03v2_lemma_aggregation")["scenarios"]
    return {s["corpus_id"]: s for s in raw}


# ---------------------------------------------------------------------------
# Parametrized invariant tests — run on EVERY scenario
# ---------------------------------------------------------------------------


class TestInvariantsAcrossAllScenarios:
    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_docs_lte_freq_invariant(self, scenario_id, scenarios):
        """docs ≤ freq must hold for every lemma in every scenario.

        Catches any refactoring that accidentally sets docs > freq (e.g.,
        counting doc appearances instead of token occurrences for freq).
        """
        scenario = scenarios[scenario_id]
        actual = simulate_aggregation(scenario["documents"])
        violations = [r for r in actual if r["docs"] > r["freq"]]
        assert not violations, f"[{scenario_id}] docs > freq violations: {violations}"

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_no_duplicate_lemmas_invariant(self, scenario_id, scenarios):
        """Each lemma must appear exactly once in aggregate output for every scenario."""
        scenario = scenarios[scenario_id]
        actual = simulate_aggregation(scenario["documents"])
        lemmas = [r["lemma"] for r in actual]
        assert len(lemmas) == len(
            set(lemmas)
        ), f"[{scenario_id}] Duplicate lemmas in output: {lemmas}"

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_total_tokens_match_invariant(self, scenario_id, scenarios):
        """sum(freq) must equal total_token_count from invariants spec."""
        scenario = scenarios[scenario_id]
        expected_total = next(
            (
                inv["total_token_count"]
                for inv in scenario.get("invariants", [])
                if inv["name"] == "total_tokens_match"
            ),
            None,
        )
        if expected_total is None:
            pytest.skip(f"[{scenario_id}] no total_tokens_match invariant defined")
        actual = simulate_aggregation(scenario["documents"])
        actual_total = sum(r["freq"] for r in actual)
        assert (
            actual_total == expected_total
        ), f"[{scenario_id}] total_tokens: expected={expected_total}, actual={actual_total}"


# ---------------------------------------------------------------------------
# Hapax scenario
# ---------------------------------------------------------------------------


class TestHapaxScenario:
    def test_hapax_validate_passes(self, scenarios):
        """C03v2_HAPAX: single-doc single-occurrence corpus passes full oracle check."""
        result = validate_lemma_aggregation(scenarios["C03v2_HAPAX"])
        assert result.match, f"C03v2_HAPAX validate failed: {result.missing}"

    def test_hapax_freq_1_docs_1(self, scenarios):
        """C03v2_HAPAX: isolated hapax lemma must have freq=1 and docs=1."""
        actual = {
            r["lemma"]: r for r in simulate_aggregation(scenarios["C03v2_HAPAX"]["documents"])
        }
        assert actual["מלך"]["freq"] == 1, f"Hapax freq must be 1. Got: {actual['מלך']['freq']}"
        assert actual["מלך"]["docs"] == 1, f"Hapax docs must be 1. Got: {actual['מלך']['docs']}"


# ---------------------------------------------------------------------------
# All-doc lemma scenario
# ---------------------------------------------------------------------------


class TestAllDocScenario:
    def test_all_doc_validate_passes(self, scenarios):
        """C03v2_ALLDOC: all-doc lemma with non-uniform per-doc frequency passes oracle."""
        result = validate_lemma_aggregation(scenarios["C03v2_ALLDOC"])
        assert result.match, f"C03v2_ALLDOC validate failed: {result.missing}"

    def test_all_doc_docs_equals_corpus_size(self, scenarios):
        """C03v2_ALLDOC: שלום (2+1+3 occurrences) must have docs == 3 (all docs).

        Non-uniform per-doc frequency (2, 1, 3) confirms no averaging confusion.
        freq=6 >> docs=3 proves the counts are tracked independently.
        """
        scenario = scenarios["C03v2_ALLDOC"]
        total_docs = len(scenario["documents"])
        actual = {r["lemma"]: r for r in simulate_aggregation(scenario["documents"])}
        assert actual["שלום"]["docs"] == total_docs, (
            f"All-doc lemma 'שלום' must have docs={total_docs}. " f"Got: {actual['שלום']['docs']}"
        )
        assert actual["שלום"]["freq"] == 6, (
            f"All-doc lemma 'שלום' must have freq=6 (2+1+3). " f"Got: {actual['שלום']['freq']}"
        )


# ---------------------------------------------------------------------------
# Empty document scenario
# ---------------------------------------------------------------------------


class TestEmptyDocScenario:
    def test_empty_doc_validate_passes(self, scenarios):
        """C03v2_EMPTYDOC: corpus with one empty document passes oracle."""
        result = validate_lemma_aggregation(scenarios["C03v2_EMPTYDOC"])
        assert result.match, f"C03v2_EMPTYDOC validate failed: {result.missing}"

    def test_empty_doc_not_counted_in_docs(self, scenarios):
        """C03v2_EMPTYDOC: ספר appears in 2 of 3 docs (DOC_B empty) → docs=2 not 3.

        By design: empty document does not inflate the docs count for any lemma.
        """
        scenario = scenarios["C03v2_EMPTYDOC"]
        actual = {r["lemma"]: r for r in simulate_aggregation(scenario["documents"])}
        assert actual["ספר"]["docs"] == 2, (
            f"Empty doc (DOC_B) must not inflate docs count. "
            f"Expected docs=2, got {actual['ספר']['docs']}"
        )
        assert actual["ספר"]["freq"] == 3, (
            f"freq must count only actual tokens (2+0+1=3). " f"Got: {actual['ספר']['freq']}"
        )


# ---------------------------------------------------------------------------
# Multi-frequency stress scenario
# ---------------------------------------------------------------------------


class TestStressScenario:
    def test_stress_validate_passes(self, scenarios):
        """C03v2_STRESS: high-freq/low-docs + all-doc + hapax all pass oracle."""
        result = validate_lemma_aggregation(scenarios["C03v2_STRESS"])
        assert result.match, f"C03v2_STRESS validate failed: {result.missing}"

    def test_stress_no_double_counting(self, scenarios):
        """C03v2_STRESS: ארץ freq=8, docs=2 — high freq does not inflate docs.

        ארץ appears 5x in DOC_A and 3x in DOC_B — total freq=8, docs=2 (not 8).
        Verifies that docs counts distinct doc_ids, not total occurrences.
        """
        actual = {
            r["lemma"]: r for r in simulate_aggregation(scenarios["C03v2_STRESS"]["documents"])
        }
        assert (
            actual["ארץ"]["freq"] == 8
        ), f"ארץ must have freq=8 (5+3). Got: {actual['ארץ']['freq']}"
        assert actual["ארץ"]["docs"] == 2, (
            f"ארץ docs must be 2 (only DOC_A and DOC_B). " f"Got: {actual['ארץ']['docs']}"
        )


# ---------------------------------------------------------------------------
# All-empty corpus scenario
# ---------------------------------------------------------------------------


class TestAllEmptyScenario:
    def test_all_empty_produces_no_aggregates(self, scenarios):
        """C03v2_ALLEMPTY: all documents have no tokens → empty aggregate output.

        By design: no tokens → no lemma rows. Total freq=0. docs ≤ freq
        vacuously holds. Oracle extra-aggregate check: 0 expected == 0 actual.
        """
        result = validate_lemma_aggregation(scenarios["C03v2_ALLEMPTY"])
        assert result.match, f"C03v2_ALLEMPTY validate failed: {result.missing}"
        actual = simulate_aggregation(scenarios["C03v2_ALLEMPTY"]["documents"])
        assert len(actual) == 0, f"All-empty corpus must produce 0 aggregates. Got: {actual}"
