"""Quality validator + sanitizer for pronunciation payloads."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class PronunciationQualityResult:
    """Sanitization result for one pronunciation text field."""

    value: Optional[str]
    is_valid: bool
    qc_flag: Optional[str]
    reason: Optional[str] = None


class PronunciationQualityService:
    """Centralized sanitizer/validator for niqqud/reading payload."""

    _MULTISPACE_RE = re.compile(r"\s+")

    @classmethod
    def sanitize_spoken_text(cls, value: Optional[str]) -> str:
        """Return safe spoken text payload (never contains `_` or `|`)."""
        text = (value or "").strip()
        if not text:
            return ""
        text = text.replace("_", " ").replace("|", " ")
        text = cls._MULTISPACE_RE.sub(" ", text).strip()
        return text

    @classmethod
    def normalize_field(
        cls,
        value: Optional[str],
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
