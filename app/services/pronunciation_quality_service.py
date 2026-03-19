"""Quality validator + sanitizer for pronunciation payloads."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass
class PronunciationQualityResult:
    """Sanitization result for one pronunciation text field."""

    value: str | None
    is_valid: bool
    qc_flag: str | None
    reason: str | None = None


@dataclass
class RemovedCodepoint:
    """Diagnostic record for removed symbols from TTS payload."""

    index: int
    char: str
    codepoint: str
    name: str
    category: str
    reason: str


class PronunciationQualityService:
    """Centralized sanitizer/validator for niqqud/reading payload."""

    _MULTISPACE_RE = re.compile(r"\s+")
    _TAAMIM_START = 0x0591
    _TAAMIM_END = 0x05AF
    _FORMAT_CODEPOINTS = {
        0x061C,  # ARABIC LETTER MARK
        0x200C,  # ZWNJ
        0x200D,  # ZWJ
        0x200E,  # LRM
        0x200F,  # RLM
        0x202A,  # LRE
        0x202B,  # RLE
        0x202C,  # PDF
        0x202D,  # LRO
        0x202E,  # RLO
        0x2060,  # WORD JOINER
        0x2066,  # LRI
        0x2067,  # RLI
        0x2068,  # FSI
        0x2069,  # PDI
        0xFEFF,  # BOM/ZWNBSP
    }
    _SEPARATORS_TO_SPACE = {
        "_",
        "-",
        "\u2010",  # hyphen
        "\u2011",  # non-breaking hyphen
        "\u2012",  # figure dash
        "\u2013",  # en dash
        "\u2014",  # em dash
        "\u2015",  # horizontal bar
        "\u05BE",  # hebrew maqaf
        "\u00A0",  # nbsp
    }
    _NIKUD_RANGES = (
        (0x05B0, 0x05BC),
        (0x05BD, 0x05BD),
        (0x05BF, 0x05BF),
        (0x05C1, 0x05C2),
        (0x05C4, 0x05C5),
        (0x05C7, 0x05C7),
    )

    @classmethod
    def _is_taamim(cls, char: str) -> bool:
        code = ord(char)
        return cls._TAAMIM_START <= code <= cls._TAAMIM_END

    @classmethod
    def _is_format_char(cls, char: str) -> bool:
        return ord(char) in cls._FORMAT_CODEPOINTS

    @classmethod
    def _removed_record(cls, *, index: int, char: str, reason: str) -> RemovedCodepoint:
        return RemovedCodepoint(
            index=index,
            char=char,
            codepoint=f"U+{ord(char):04X}",
            name=unicodedata.name(char, "UNKNOWN"),
            category=unicodedata.category(char),
            reason=reason,
        )

    @classmethod
    def sanitize_tts_text_with_meta(cls, value: str | None) -> tuple[str, list[RemovedCodepoint]]:
        """Return sanitized TTS text and removed codepoint diagnostics."""
        text = (value or "").strip()
        if not text:
            return "", []

        removed: list[RemovedCodepoint] = []
        out_chars: list[str] = []
        for index, char in enumerate(text):
            if cls._is_taamim(char):
                removed.append(cls._removed_record(index=index, char=char, reason="taamim"))
                continue
            if cls._is_format_char(char):
                removed.append(cls._removed_record(index=index, char=char, reason="format_char"))
                continue
            if char == "|":
                removed.append(cls._removed_record(index=index, char=char, reason="pipe_to_space"))
                out_chars.append(" ")
                continue
            if char in cls._SEPARATORS_TO_SPACE:
                out_chars.append(" ")
                continue
            out_chars.append(char)

        normalized = unicodedata.normalize("NFC", "".join(out_chars))
        normalized = cls._MULTISPACE_RE.sub(" ", normalized).strip()
        return normalized, removed

    @classmethod
    def sanitize_tts_text(cls, value: str | None) -> str:
        """Return safe spoken text payload for provider requests."""
        sanitized, _removed = cls.sanitize_tts_text_with_meta(value)
        return sanitized

    @classmethod
    def sanitize_spoken_text(cls, value: str | None) -> str:
        """Backward-compatible alias for sanitizer used in spoken payloads."""
        return cls.sanitize_tts_text(value)

    @classmethod
    def normalize_field(
        cls,
        value: str | None,
        *,
        strict: bool,
    ) -> PronunciationQualityResult:
        """Normalize one field and return QC metadata.

        `strict=True` rejects hard separators (`|`) for manual inputs.
        """
        raw = (value or "").strip()
        if not raw:
            return PronunciationQualityResult(value=None, is_valid=True, qc_flag=None)

        if strict and "|" in raw:
            return PronunciationQualityResult(
                value=None,
                is_valid=False,
                qc_flag="rejected",
                reason="Character '|' is not allowed in strict mode.",
            )

        sanitized = cls.sanitize_spoken_text(raw)
        if not sanitized:
            return PronunciationQualityResult(
                value=None,
                is_valid=False,
                qc_flag="rejected",
                reason="Pronunciation text became empty after sanitization.",
            )

        if sanitized != raw:
            return PronunciationQualityResult(
                value=sanitized,
                is_valid=True,
                qc_flag="auto_fixed",
            )

        return PronunciationQualityResult(value=sanitized, is_valid=True, qc_flag=None)

    @classmethod
    def has_hebrew_nikud(cls, value: str | None) -> bool:
        """Return True when value contains Hebrew vowel/diacritic marks."""
        text = (value or "").strip()
        if not text:
            return False
        for char in text:
            code = ord(char)
            for start, end in cls._NIKUD_RANGES:
                if start <= code <= end:
                    return True
        return False

    @classmethod
    def spoken_letters_signature(cls, value: str | None) -> str:
        """Return comparable signature without diacritics/formatting noise."""
        sanitized = cls.sanitize_tts_text(value)
        if not sanitized:
            return ""
        chars: list[str] = []
        for char in sanitized:
            category = unicodedata.category(char)
            if category.startswith("M"):
                continue
            if char.isspace():
                chars.append(" ")
                continue
            if category.startswith("L") or category.startswith("N"):
                chars.append(char)
        return cls._MULTISPACE_RE.sub(" ", "".join(chars)).strip()

    @classmethod
    def has_source_structure_mismatch(
        cls, source_text: str | None, candidate_text: str | None
    ) -> bool:
        """Detect when generated pronunciation drops/adds source letters/tokens."""
        source_sig = cls.spoken_letters_signature(source_text)
        candidate_sig = cls.spoken_letters_signature(candidate_text)
        if not source_sig or not candidate_sig:
            return False
        return source_sig != candidate_sig
