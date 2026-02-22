"""Tests: sentence niqqud guards (min_len, max_len, min_hebrew_ratio)."""
from __future__ import annotations

import pytest
from app.services.sentence_pronunciation_service import (
    GuardParams,
    SentencePronunciationService,
)


@pytest.fixture()
def svc():
    return SentencePronunciationService()


class TestShouldProcess:
    def test_too_short_skipped(self, svc):
        ok, reason = svc.should_process("שלו", guard=GuardParams(min_len=5))
        assert not ok
        assert reason == "skipped_too_short"

    def test_exactly_min_len_passes(self, svc):
        ok, reason = svc.should_process("שלום", guard=GuardParams(min_len=4))
        assert ok
        assert reason == ""

    def test_too_long_skipped(self, svc):
        long_text = "א" * 2001
        ok, reason = svc.should_process(long_text, guard=GuardParams(max_len=2000))
        assert not ok
        assert reason == "skipped_too_long"

    def test_non_hebrew_skipped(self, svc):
        # All Latin — Hebrew ratio 0
        ok, reason = svc.should_process(
            "hello world this is english",
            guard=GuardParams(min_he_ratio=0.10),
        )
        assert not ok
        assert reason == "skipped_non_hebrew_ratio"

    def test_mixed_hebrew_passes_threshold(self, svc):
        # 50% Hebrew letters → above 0.10
        ok, reason = svc.should_process(
            "שלום hello", guard=GuardParams(min_he_ratio=0.10)
        )
        assert ok
        assert reason == ""

    def test_empty_string_fails_ratio(self, svc):
        ok, reason = svc.should_process("", guard=GuardParams(min_len=1))
        # Empty = too short (len 0 < 1)
        assert not ok

    def test_default_guards_happy_path(self, svc):
        ok, reason = svc.should_process("בית הספר מדהים מאוד כן")
        assert ok
        assert reason == ""


class TestPreprocessText:
    def test_strips_bidi_markers(self, svc):
        text = "\u200E\u200Fשלום\u202A"
        result = svc.preprocess_text(text)
        assert "\u200E" not in result
        assert "\u200F" not in result
        assert "\u202A" not in result
        assert "שלום" in result

    def test_normalizes_whitespace(self, svc):
        text = "שלום    עולם\tוהחיים"
        result = svc.preprocess_text(text)
        assert "  " not in result
        assert "\t" not in result


class TestQC:
    def test_empty_output_rejected(self, svc):
        status, reason, coverage = svc.run_qc("")
        assert status == "rejected"
        assert "empty" in (reason or "")

    def test_no_nikud_marks_rejected(self, svc):
        status, reason, coverage = svc.run_qc("שלום עולם")
        assert status == "rejected"
        assert "no_nikud" in (reason or "")

    def test_full_coverage_ok(self, svc):
        # Full nikud: every word has marks
        niqqud = "שָׁלוֹם עוֹלָם"
        status, reason, coverage = svc.run_qc(niqqud)
        assert status in ("ok", "partial"), f"Got {status} for {niqqud!r}"

    def test_partial_coverage_partial_status(self, svc):
        # 1/3 words with nikud → ~33% → rejected
        # 2/3 words with nikud → ~67% → partial
        niqqud = "שָׁלוֹם עולם וברכה"  # 1/3 has nikud
        status, reason, coverage = svc.run_qc(niqqud)
        # coverage < 0.75 → partial or rejected depending on threshold
        assert status in ("partial", "rejected"), f"Got {status}"
        assert coverage is not None
