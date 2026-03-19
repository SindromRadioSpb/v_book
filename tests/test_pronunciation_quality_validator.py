"""Tests for pronunciation quality validator strict/autofix policies."""

from app.services.pronunciation_quality_service import PronunciationQualityService


def test_strict_rejects_pipe_separator():
    result = PronunciationQualityService.normalize_field(
        "\u05d9\u05e9\u05d5\u05e8|\u05d5\u05e4\u05e2", strict=True
    )
    assert result.is_valid is False
    assert result.qc_flag == "rejected"


def test_strict_autofixes_underscore():
    result = PronunciationQualityService.normalize_field(
        "\u05ea\u05d7\u05e0\u05d4_\u05d1\u05d0\u05d4", strict=True
    )
    assert result.is_valid is True
    assert result.value == "\u05ea\u05d7\u05e0\u05d4 \u05d1\u05d0\u05d4"
    assert result.qc_flag == "auto_fixed"


def test_autofix_mode_keeps_valid_output_for_pipe():
    result = PronunciationQualityService.normalize_field(
        "\u05de\u05d9\u05e9\u05d5\u05e8|\u05de\u05e9\u05d5\u05e4\u05e2", strict=False
    )
    assert result.is_valid is True
    assert result.value == "\u05de\u05d9\u05e9\u05d5\u05e8 \u05de\u05e9\u05d5\u05e4\u05e2"
    assert result.qc_flag == "auto_fixed"


def test_detects_source_structure_mismatch():
    assert (
        PronunciationQualityService.has_source_structure_mismatch(
            "\u05e4\u05e8\u05e7 \u05d4\u05d6\u05de\u05df", "\u05e4\u05e8\u05e7 \u05d6\u05de\u05df"
        )
        is True
    )
    assert (
        PronunciationQualityService.has_source_structure_mismatch(
            "\u05e4\u05e8\u05e7 \u05d6\u05de\u05df",
            "\u05e4\u05b6\u05bc\u05e8\u05b6\u05e7 \u05d6\u05b0\u05de\u05b7\u05df",
        )
        is False
    )


def test_has_hebrew_nikud_detects_marks():
    assert (
        PronunciationQualityService.has_hebrew_nikud("\u05e4\u05b6\u05bc\u05e8\u05b6\u05e7") is True
    )
    assert PronunciationQualityService.has_hebrew_nikud("\u05e4\u05e8\u05e7") is False
