"""V08v2 — Noise classifier borderline cases and boundary contracts (C08v2).

Extends C08 with:
  - Mixed-script inputs: "Q1" (Latin+digit), "א3" (Hebrew+digit)
  - Latin acronym: "PDF" — WORD_LATIN, not noise
  - Short Hebrew word: "אב" — WORD_HE, not noise (default classifier)
  - Ratio-check boundary: len>2 required for NOISE_RATIO_NON_LETTER_HIGH
    • "12" (len=2) → NOISE_NUMERIC_ONLY (ratio check suppressed)
    • "a1234" (len=5, ratio=0.8) → NOISE_RATIO_NON_LETTER_HIGH (fires)
  - Empty string → PUNCT / NOISE_PUNCT_ONLY
  - Phrase ≥50% threshold: exactly 50% (2/4 tokens) → IS noise (inclusive)
  - Phrase 25% (1/4 tokens) → NOT noise
  - Multi-word Latin phrase → NOT noise

Profile note:
  conservative/balanced/aggressive profiles are NOT implemented as a filter API
  in entity_classifier.py. They are conceptual documentation only. The classifier
  is profile-agnostic — no profile parameter exists. Profile-specific filtering
  is a missing post-classification layer. See C08v2 gold for details.

No Stanza required — pure Python classifier.
"""

from __future__ import annotations

import pytest

from app.services.entity_classifier import classify_phrase, classify_text
from tests.validation.oracles.oracle_noise import (
    validate_classify_phrase,
    validate_classify_text,
)


@pytest.fixture
def text_cases(gold_data):
    return gold_data("c08v2_noise_borderline")["classify_text_cases"]


@pytest.fixture
def phrase_cases(gold_data):
    return gold_data("c08v2_noise_borderline")["classify_phrase_cases"]


# ---------------------------------------------------------------------------
# Borderline classify_text cases
# ---------------------------------------------------------------------------


class TestBorderlineClassifyText:
    def test_all_borderline_text_cases_pass(self, text_cases):
        failures = []
        for case in text_cases:
            result = validate_classify_text(case)
            if not result.match:
                failures.append(
                    {
                        "case_id": result.case_id,
                        "expected": result.expected,
                        "actual": result.actual,
                        "details": result.missing,
                    }
                )
        assert not failures, f"classify_text borderline failures:\n{failures}"

    def test_latin_acronym_not_noise(self, text_cases):
        """C08v2_01: 'PDF' — Latin acronym is WORD_LATIN, not noise."""
        c = next(c for c in text_cases if c["case_id"] == "C08v2_01")
        result = validate_classify_text(c)
        assert not result.actual["is_noise"], "'PDF' must not be noise"
        assert result.actual["entity_class"] == "WORD_LATIN"

    def test_mixed_latin_digit_is_noise(self, text_cases):
        """C08v2_02: 'Q1' — Latin+digit → MIXED_ALPHA_NUM, noise."""
        c = next(c for c in text_cases if c["case_id"] == "C08v2_02")
        result = validate_classify_text(c)
        assert result.actual["is_noise"], "'Q1' must be noise"
        assert result.actual["entity_class"] == "MIXED_ALPHA_NUM"

    def test_mixed_hebrew_digit_is_noise(self, text_cases):
        """C08v2_03: 'א3' — Hebrew+digit → MIXED_ALPHA_NUM, noise."""
        c = next(c for c in text_cases if c["case_id"] == "C08v2_03")
        result = validate_classify_text(c)
        assert result.actual["is_noise"], "'א3' must be noise"
        assert result.actual["entity_class"] == "MIXED_ALPHA_NUM"

    def test_two_char_hebrew_not_noise(self, text_cases):
        """C08v2_04: 'אב' — 2-char Hebrew → WORD_HE, not noise at default classifier.

        The aggressive profile (not implemented) would add a len<=2 rule for WORD_HE.
        The default classifier has no such rule.
        """
        c = next(c for c in text_cases if c["case_id"] == "C08v2_04")
        result = validate_classify_text(c)
        assert not result.actual["is_noise"], "'אב' must not be noise at default classifier"
        assert result.actual["entity_class"] == "WORD_HE"

    def test_high_digit_ratio_fires_ratio_check(self, text_cases):
        """C08v2_05: 'a1234' — digit_ratio=0.8 > 0.6 and len=5 > 2 → NOISE_RATIO_NON_LETTER_HIGH."""
        c = next(c for c in text_cases if c["case_id"] == "C08v2_05")
        result = validate_classify_text(c)
        assert result.actual["noise_reason"] == "NOISE_RATIO_NON_LETTER_HIGH"

    def test_short_number_uses_class_mapping_not_ratio(self, text_cases):
        """C08v2_06: '12' — len=2 suppresses NOISE_RATIO_NON_LETTER_HIGH; uses NOISE_NUMERIC_ONLY.

        Contrast with C08_03 ('123', len=3) → NOISE_RATIO_NON_LETTER_HIGH.
        The ratio check condition is: len > 2 AND ratio > 0.6.
        At len=2 the ratio check is explicitly suppressed.
        """
        c = next(c for c in text_cases if c["case_id"] == "C08v2_06")
        result = validate_classify_text(c)
        assert result.actual["noise_reason"] == "NOISE_NUMERIC_ONLY", (
            "'12' noise_reason must be NOISE_NUMERIC_ONLY — "
            "ratio check requires len>2 which '12' does not satisfy"
        )

    def test_empty_string_is_punct_noise(self, text_cases):
        """C08v2_07: Empty string → PUNCT, NOISE_PUNCT_ONLY (before decision tree)."""
        c = next(c for c in text_cases if c["case_id"] == "C08v2_07")
        result = validate_classify_text(c)
        assert result.actual["is_noise"]
        assert result.actual["entity_class"] == "PUNCT"
        assert result.actual["noise_reason"] == "NOISE_PUNCT_ONLY"


# ---------------------------------------------------------------------------
# Phrase threshold boundary
# ---------------------------------------------------------------------------


class TestPhraseThresholdBoundary:
    def test_all_borderline_phrase_cases_pass(self, phrase_cases):
        failures = []
        for case in phrase_cases:
            result = validate_classify_phrase(case)
            if not result.match:
                failures.append(
                    {
                        "case_id": result.case_id,
                        "expected": result.expected,
                        "actual": result.actual,
                        "details": result.missing,
                    }
                )
        assert not failures, f"classify_phrase borderline failures:\n{failures}"

    def test_exactly_50_percent_noise_tokens_is_noise(self, phrase_cases):
        """C08v2_P01: phrase with exactly 2/4 noise tokens IS noise (threshold >=0.5 inclusive).

        This pins the threshold direction: the condition is noise_count/total >= 0.5,
        not > 0.5. At the boundary, the phrase is classified as noise.
        """
        c = next(c for c in phrase_cases if c["case_id"] == "C08v2_P01")
        result = validate_classify_phrase(c)
        assert result.actual[
            "is_noise"
        ], "Phrase with 2/4 (50%) noise tokens must be noise — threshold is >=0.5 inclusive"

    def test_25_percent_noise_tokens_not_noise(self, phrase_cases):
        """C08v2_P02: phrase with 1/4 noise tokens is NOT noise."""
        c = next(c for c in phrase_cases if c["case_id"] == "C08v2_P02")
        result = validate_classify_phrase(c)
        assert not result.actual["is_noise"], "1/4 noise tokens (25%) must not trigger phrase noise"

    def test_multi_word_latin_phrase_not_noise(self, phrase_cases):
        """C08v2_P03: multi-word Latin phrase is NOT noise."""
        c = next(c for c in phrase_cases if c["case_id"] == "C08v2_P03")
        result = validate_classify_phrase(c)
        assert not result.actual["is_noise"], "Latin phrase must not be noise"


# ---------------------------------------------------------------------------
# Ratio check boundary contract
# ---------------------------------------------------------------------------


class TestRatioCheckBoundary:
    def test_ratio_check_requires_len_greater_than_2(self):
        """NOISE_RATIO_NON_LETTER_HIGH fires only when len > 2 (not len == 2).

        This is an explicit len>2 guard in the classifier. At len=2 with high
        non-letter ratio, the class-mapping reason is used instead.
        """
        r_short = classify_text("12")  # len=2, digit_ratio=1.0
        r_long = classify_text("123")  # len=3, digit_ratio=1.0

        assert (
            r_short.noise_reason != "NOISE_RATIO_NON_LETTER_HIGH"
        ), "len=2 must NOT trigger NOISE_RATIO_NON_LETTER_HIGH"
        assert (
            r_long.noise_reason == "NOISE_RATIO_NON_LETTER_HIGH"
        ), "len=3 with full digit content MUST trigger NOISE_RATIO_NON_LETTER_HIGH"

    def test_ratio_check_fires_when_ratio_above_0_6(self):
        """NOISE_RATIO_NON_LETTER_HIGH fires when non_letter_ratio > 0.6 AND len > 2."""
        r = classify_text("a1234")  # digit_ratio=0.8, len=5
        assert r.noise_reason == "NOISE_RATIO_NON_LETTER_HIGH"
        assert r.is_noise

    def test_ratio_check_suppressed_when_ratio_below_threshold(self):
        """NOISE_RATIO_NON_LETTER_HIGH does NOT fire when ratio <= 0.6.

        'abc12' has digit_ratio=2/5=0.4 — below the 0.6 threshold.
        The MIXED_ALPHA_NUM class mapping fires instead.
        """
        r = classify_text("abc12")  # digit_ratio=0.4, len=5
        assert r.is_noise
        assert (
            r.noise_reason == "NOISE_MIXED_GARBAGE"
        ), "ratio=0.4 is below 0.6 threshold — NOISE_MIXED_GARBAGE from class mapping expected"


# ---------------------------------------------------------------------------
# Profile architecture contract
# ---------------------------------------------------------------------------


class TestProfileArchitectureContract:
    def test_classify_text_has_no_profile_parameter(self):
        """classify_text() is profile-agnostic: no profile/mode parameter.

        The conservative/balanced/aggressive profiles in the gold corpus are
        conceptual definitions. They are NOT implemented as a filter API.
        Any profile-specific filtering must happen at a higher application layer.
        """
        import inspect

        sig = inspect.signature(classify_text)
        param_names = list(sig.parameters.keys())
        assert "profile" not in param_names, (
            "classify_text() must not have a 'profile' parameter — "
            "profiles are not implemented in the classifier layer"
        )
        assert (
            len(param_names) == 1
        ), f"classify_text() must accept exactly 1 parameter (raw), got: {param_names}"

    def test_classify_phrase_has_no_profile_parameter(self):
        """classify_phrase() is profile-agnostic: no profile/mode parameter."""
        import inspect

        sig = inspect.signature(classify_phrase)
        param_names = list(sig.parameters.keys())
        assert "profile" not in param_names
        assert len(param_names) == 1

    def test_two_char_hebrew_is_not_noise_without_profile(self):
        """'אב' is NOT noise at the default (profile-agnostic) classifier level.

        An aggressive-profile filter layer would override this. Since that layer
        does not exist, the classifier returns is_noise=False for 'אב'.
        This test pins the default contract so any future profile implementation
        can be verified against it.
        """
        r = classify_text("אב")
        assert not r.is_noise
        assert r.entity_class == "WORD_HE"
