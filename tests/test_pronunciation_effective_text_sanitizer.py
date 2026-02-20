"""Tests for pronunciation effective spoken text sanitization."""

from app.services.pronunciation_quality_service import PronunciationQualityService


def test_sanitize_replaces_underscores_and_pipes():
    text = "תחנה_באה|עוד"
    sanitized = PronunciationQualityService.sanitize_spoken_text(text)
    assert "_" not in sanitized
    assert "|" not in sanitized
    assert sanitized == "תחנה באה עוד"


def test_sanitize_collapses_whitespace():
    text = "  מישור__  המשופע  |   נוסף  "
    sanitized = PronunciationQualityService.sanitize_spoken_text(text)
    assert sanitized == "מישור המשופע נוסף"
