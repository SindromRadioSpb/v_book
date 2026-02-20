"""Tests for TTS payload sanitizer (taamim + formatting chars)."""

from app.services.pronunciation_quality_service import PronunciationQualityService


def test_sanitize_tts_text_removes_taamim_and_keeps_niqqud():
    # רַ֫כֶב : includes taamim U+05AB that must be removed.
    raw = "\u05E8\u05B7\u05AB\u05DB\u05B6\u05D1"
    sanitized = PronunciationQualityService.sanitize_tts_text(raw)

    assert "\u05AB" not in sanitized
    assert "\u05B7" in sanitized
    assert "\u05B6" in sanitized
    assert sanitized == "\u05E8\u05B7\u05DB\u05B6\u05D1"


def test_sanitize_tts_text_removes_bidi_and_joiners_and_normalizes_separators():
    # Contains RLM/ZWJ/LRI+PDI + underscore + pipe + dash.
    raw = "\u05DE\u05D5\u05EA\u05E8\u05EA_\u200F\u200D\u2066\u2069|\u2013\u05D1"
    sanitized = PronunciationQualityService.sanitize_tts_text(raw)

    assert "\u200F" not in sanitized
    assert "\u200D" not in sanitized
    assert "\u2066" not in sanitized
    assert "\u2069" not in sanitized
    assert "_" not in sanitized
    assert "|" not in sanitized
    assert "\u2013" not in sanitized
    assert sanitized == "\u05DE\u05D5\u05EA\u05E8\u05EA \u05D1"

