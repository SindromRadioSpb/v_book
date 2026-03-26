"""V05v2 — NP chunk extraction edge cases: DET in non-first position,
multiple DET tokens, and ADJ-led NP spans (C05v2).

Extends C05 with:
  - DET in non-first position: DET is NOT in STOP_POS (does not break segment),
    but _is_valid_np_span rejects any span where DET appears at a non-first
    position (DET not in CORE_NP_POS or MODIFIER_POS). Sub-span starting AT
    the DET position remains valid.
  - Multiple standalone DET tokens: second DET blocks all bridge spans;
    only the first [DET, NOUN] bigram is extracted.
  - ADJ-led NP span: ADJ is in MODIFIER_POS; is_valid_np_token(ADJ, is_first=True)
    → True, so ADJ can open a segment without a preceding DET.
  - C05_07 exact-match verification: the 5-token all-nominal case yields
    exactly 9 chunks (converted from subset match in C05 v2).

No implementation changes — all gaps were gold/test coverage gaps.
No Stanza required.
"""

from __future__ import annotations

import pytest

from app.domain.term_extraction.np_extractor import (
    _is_valid_np_span,
    extract_np_chunks_from_sentence,
)
from tests.validation.oracles.oracle_np import validate_np_extraction


@pytest.fixture
def cases(gold_data):
    return gold_data("c05v2_np_extraction")["cases"]


@pytest.fixture
def c05_cases(gold_data):
    """Access original C05 gold to verify C05_07 exact-match update."""
    return gold_data("c05_np_extraction")["cases"]


# ---------------------------------------------------------------------------
# DET in non-first position
# ---------------------------------------------------------------------------


class TestDetNonFirstPosition:
    def test_is_valid_np_span_rejects_det_at_non_first(self):
        """_is_valid_np_span must reject spans where DET appears at non-first position.

        DET is not in CORE_NP_POS or MODIFIER_POS — the non-first token loop
        returns False for any DET at position 1+.
        """
        assert not _is_valid_np_span(
            ["NOUN", "DET"]
        ), "NOUN+DET span must be rejected (DET not allowed at non-first position)"
        assert not _is_valid_np_span(
            ["NOUN", "DET", "NOUN"]
        ), "NOUN+DET+NOUN span must be rejected (DET at position 1)"

    def test_is_valid_np_span_allows_det_at_first(self):
        """_is_valid_np_span must accept spans where DET is the first token.

        is_valid_np_token(DET, is_first=True) returns True. The span also needs
        at least one CORE_NP_POS token to pass the has_core check.
        """
        assert _is_valid_np_span(
            ["DET", "NOUN"]
        ), "DET+NOUN span must be accepted (DET allowed at first position)"

    def test_det_non_first_gold_case(self, cases):
        """C05v2_01: [ספר(NOUN), ה(DET), ילד(NOUN)] — only 'הילד' sub-span extracted.

        Spans containing DET at non-first position are rejected. The sub-span
        [ה, ילד] starting AT the DET position is valid → merge → 'הילד'.
        """
        c = next(c for c in cases if c["case_id"] == "C05v2_01")
        result = validate_np_extraction(c)
        assert (
            result.match
        ), f"C05v2_01 DET non-first failed: missing={result.missing}, extra={result.extra}"

    def test_det_non_first_exactly_one_chunk(self, cases):
        """C05v2_01: exactly 1 chunk extracted — only the [ה,ילד] sub-span."""
        c = next(c for c in cases if c["case_id"] == "C05v2_01")
        result = validate_np_extraction(c)
        assert (
            result.actual == 1
        ), f"C05v2_01 must produce exactly 1 chunk (sub-span [ה,ילד]). Got: {result.actual}"


# ---------------------------------------------------------------------------
# Multiple standalone DET tokens
# ---------------------------------------------------------------------------


class TestMultipleDet:
    def test_multiple_det_exact_match(self, cases):
        """C05v2_02: [ה, ילד, ה, גדול] — second DET blocks all bridge spans; 1 chunk only."""
        c = next(c for c in cases if c["case_id"] == "C05v2_02")
        result = validate_np_extraction(c)
        assert (
            result.match
        ), f"C05v2_02 multiple DET failed: missing={result.missing}, extra={result.extra}"

    def test_multiple_det_produces_one_chunk(self, cases):
        """C05v2_02: exactly 1 chunk (הילד) — second DET prevents any bridge span."""
        c = next(c for c in cases if c["case_id"] == "C05v2_02")
        result = validate_np_extraction(c)
        assert (
            result.actual == 1
        ), f"Multiple DET input must produce exactly 1 chunk. Got: {result.actual}"


# ---------------------------------------------------------------------------
# ADJ-led NP span
# ---------------------------------------------------------------------------


class TestAdjLedNP:
    def test_modifier_pos_can_open_span(self):
        """ADJ is in MODIFIER_POS; is_valid_np_token(ADJ, is_first=True) → True.

        Pins the contract that MODIFIER_POS tokens can open a segment without
        a preceding DET. This is by design — Hebrew NPs can begin with an adjective.
        """
        assert _is_valid_np_span(
            ["ADJ", "NOUN"]
        ), "ADJ+NOUN span must be accepted (ADJ in MODIFIER_POS → valid first token)"
        assert _is_valid_np_span(["ADJ", "NOUN", "NOUN"]), "ADJ+NOUN+NOUN span must be accepted"

    def test_adj_led_np_gold_case(self, cases):
        """C05v2_03: [ישן(ADJ), בית(NOUN), ספר(NOUN)] — 3 chunks including ADJ-led spans."""
        c = next(c for c in cases if c["case_id"] == "C05v2_03")
        result = validate_np_extraction(c)
        assert (
            result.match
        ), f"C05v2_03 ADJ-led NP failed: missing={result.missing}, extra={result.extra}"


# ---------------------------------------------------------------------------
# C05_07 exact-match verification (5-token all-nominal case)
# ---------------------------------------------------------------------------


class TestFiveTokenExactness:
    def test_five_token_exact_count_nine(self, c05_cases):
        """C05_07 (updated): 5-token NOUN×3+ADJ×2 input yields exactly 9 chunks.

        Converted from subset match (min_count=7) to exact match (9 chunks) in C05 v2.
        This closes the phantom-chunk gap: if the extractor were to produce extra
        unexpected chunks, this test would catch them as 'extra' in the oracle.

        Exact set: 3 bigrams (ADJ+ADJ at [3,4] rejected — no CORE_NP),
                   3 trigrams, 2 quadrigrams, 1 quintgram.
        """
        c = next(c for c in c05_cases if c["case_id"] == "C05_07")
        result = validate_np_extraction(c)
        assert (
            result.match
        ), f"C05_07 exact match failed: missing={result.missing}, extra={result.extra}"
        assert result.actual == 9, f"C05_07 must produce exactly 9 chunks. Got: {result.actual}"

    def test_adj_adj_span_no_core_rejected(self):
        """ADJ+ADJ span is invalid — has no CORE_NP (NOUN/PROPN).

        Pins why the ADJ+ADJ bigram at positions [3,4] in C05_07 is not extracted.
        _is_valid_np_span requires at least one CORE_NP_POS; ADJ is MODIFIER_POS only.
        """
        assert not _is_valid_np_span(
            ["ADJ", "ADJ"]
        ), "ADJ+ADJ span must be rejected (no CORE_NP_POS token)"


# ---------------------------------------------------------------------------
# Full bulk pass + determinism
# ---------------------------------------------------------------------------


class TestAllC05v2Cases:
    def test_all_c05v2_cases_pass(self, cases):
        """All 3 C05v2 gold cases must pass exact oracle match."""
        failures = []
        for case in cases:
            result = validate_np_extraction(case)
            if not result.match:
                failures.append(
                    {
                        "case_id": result.case_id,
                        "missing": result.missing,
                        "extra": result.extra,
                    }
                )
        assert not failures, f"C05v2 NP extraction failures:\n{failures}"

    def test_determinism_on_new_cases(self, cases):
        """All C05v2 cases must be deterministic."""
        for case in cases:
            tokens = case["input"]["tokens"]
            min_len = case["input"].get("min_len", 2)
            max_len = case["input"].get("max_len", 5)
            r1 = extract_np_chunks_from_sentence(tokens, min_len=min_len, max_len=max_len)
            r2 = extract_np_chunks_from_sentence(tokens, min_len=min_len, max_len=max_len)
            assert r1 == r2, f"Non-deterministic NP extraction for case '{case['case_id']}'"
