"""V08 — Noise classification validation (C08).

Tests classify_text() and classify_phrase() against gold expected values.
No Stanza required — pure Python classifier.
"""

from __future__ import annotations

import pytest

from tests.validation.oracles.oracle_noise import (
    validate_classify_phrase,
    validate_classify_text,
)


@pytest.fixture
def text_cases(gold_data):
    return gold_data("c08_noise_classification")["classify_text_cases"]


@pytest.fixture
def phrase_cases(gold_data):
    return gold_data("c08_noise_classification")["classify_phrase_cases"]


class TestClassifyText:
    def test_all_text_cases_pass(self, text_cases):
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
        assert not failures, f"classify_text failures:\n{failures}"

    def test_hebrew_word_not_noise(self, text_cases):
        """Hebrew words must not be classified as noise."""
        for case in text_cases:
            if case["expected"].get("entity_class") == "WORD_HE" and not case["expected"].get(
                "is_noise"
            ):
                result = validate_classify_text(case)
                assert not result.actual[
                    "is_noise"
                ], f"Case {case['case_id']}: Hebrew word '{case['input']}' should not be noise"

    def test_punctuation_is_noise(self, text_cases):
        """Pure punctuation must be classified as noise."""
        c = next(c for c in text_cases if c["case_id"] == "C08_02")
        result = validate_classify_text(c)
        assert result.actual["is_noise"], f"Punctuation '...' should be noise"

    def test_number_is_noise(self, text_cases):
        """Pure numbers must be classified as noise."""
        c = next(c for c in text_cases if c["case_id"] == "C08_03")
        result = validate_classify_text(c)
        assert result.actual["is_noise"], f"Number '123' should be noise"

    def test_latin_word_not_noise(self, text_cases):
        """Latin words must not be classified as noise."""
        c = next(c for c in text_cases if c["case_id"] == "C08_04")
        result = validate_classify_text(c)
        assert not result.actual["is_noise"], f"Latin word 'Israel' should not be noise"

    def test_determinism(self):
        """Same input must produce same classification on two calls."""
        from app.services.entity_classifier import classify_text

        r1 = classify_text("ירושלים")
        r2 = classify_text("ירושלים")
        assert r1 == r2, "classify_text is non-deterministic"


class TestClassifyPhrase:
    def test_all_phrase_cases_pass(self, phrase_cases):
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
        assert not failures, f"classify_phrase failures:\n{failures}"

    def test_hebrew_phrase_not_noise(self, phrase_cases):
        """C08_P01: Hebrew phrase must not be noise."""
        c = next(c for c in phrase_cases if c["case_id"] == "C08_P01")
        result = validate_classify_phrase(c)
        assert not result.actual["is_noise"], f"Hebrew phrase should not be noise"

    def test_all_noise_tokens_phrase_is_noise(self, phrase_cases):
        """C08_P02: Phrase with all noise tokens must be noise."""
        c = next(c for c in phrase_cases if c["case_id"] == "C08_P02")
        result = validate_classify_phrase(c)
        assert result.actual["is_noise"], f"All-noise phrase should be noise"


class TestNoiseInvariants:
    def test_noise_source_not_set_by_classifier(self):
        """classify_text() returns entity_class/is_noise/noise_reason only — no noise_source."""
        from app.services.entity_classifier import classify_text

        result = classify_text("ירושלים")
        assert not hasattr(
            result, "noise_source"
        ), "classify_text() must not set noise_source — that is a write-path concern"

    def test_auto_not_manual_noise_reason(self):
        """NoiseReason codes are constants — no 'manual' reason code exists."""
        from app.services.entity_classifier import NoiseReason

        reason_values = [r.value for r in NoiseReason]
        assert (
            "manual" not in reason_values
        ), "NoiseReason must not include 'manual' — that is a noise_source axis, not reason"
