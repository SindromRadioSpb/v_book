"""Tests for pronunciation quality validator strict/autofix policies."""

from app.services.pronunciation_quality_service import PronunciationQualityService


def test_strict_rejects_pipe_separator():
    result = PronunciationQualityService.normalize_field("ישור|ופע", strict=True)
    assert result.is_valid is False
    assert result.qc_flag == "rejected"


def test_strict_autofixes_underscore():
    result = PronunciationQualityService.normalize_field("תחנה_באה", strict=True)
    assert result.is_valid is True
    assert result.value == "תחנה באה"
    assert result.qc_flag == "auto_fixed"


def test_autofix_mode_keeps_valid_output_for_pipe():
    result = PronunciationQualityService.normalize_field("מישור|משופע", strict=False)
    assert result.is_valid is True
    assert result.value == "מישור משופע"
    assert result.qc_flag == "auto_fixed"
