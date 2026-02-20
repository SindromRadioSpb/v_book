"""Diagnostics-oriented checks for TTS payload codepoints."""

from __future__ import annotations

import unicodedata

from app.services.pronunciation_quality_service import PronunciationQualityService


def _has_disallowed_codepoints(text: str) -> bool:
    for char in text:
        cp = ord(char)
        if 0x0591 <= cp <= 0x05AF:
            return True
        if cp in {
            0x061C,
            0x200C,
            0x200D,
            0x200E,
            0x200F,
            0x202A,
            0x202B,
            0x202C,
            0x202D,
            0x202E,
            0x2060,
            0x2066,
            0x2067,
            0x2068,
            0x2069,
            0xFEFF,
        }:
            return True
    return False


def test_sanitized_payload_has_no_taamim_or_bidi_and_keeps_niqqud():
    # מֻ֛תָּרֶת + format chars + separators.
    raw = (
        "\u05DE\u05BB\u059B\u05EA\u05B8\u05BC\u05E8\u05B6\u05EA"
        "\u200F_\u200D|\u2066\u2069-\u05DE\u05B7\u05DB\u05B6\u05D1"
    )

    sanitized, removed = PronunciationQualityService.sanitize_tts_text_with_meta(raw)

    assert not _has_disallowed_codepoints(sanitized)
    # Keep niqqud marks in sanitized output.
    assert "\u05BB" in sanitized
    assert "\u05B8" in sanitized
    assert "\u05BC" in sanitized
    assert "\u05B6" in sanitized
    assert "\u05B7" in sanitized
    # Ensure taamim was removed.
    assert "\u059B" not in sanitized
    # Ensure removed diagnostics includes expected categories.
    reasons = {item.reason for item in removed}
    assert "taamim" in reasons
    assert "format_char" in reasons
    assert "pipe_removed" in reasons

    # Sanity check: niqqud characters are combining marks.
    niqqud_categories = [unicodedata.category(ch) for ch in sanitized if 0x05B0 <= ord(ch) <= 0x05BC]
    assert niqqud_categories
    assert all(cat == "Mn" for cat in niqqud_categories)

