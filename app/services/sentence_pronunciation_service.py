"""Sentence pronunciation service — dedicated sentence-level niqqud layer.

Key contract:
- Keyed by sentence_id (not by src_norm).
- src_hash = sha256(lang|preprocessed_text|phonikud_version|sanitizer_version) for idempotency.
- Manual override (is_override=1) is NEVER auto-overwritten.
- QC tiers: ok (>=0.75 coverage), partial (0.40-0.75), rejected (<0.40), failed (error).
- See docs/SENTENCES_NIQQUD.md for full contract.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.dto import SentenceNiqqudOverlay
from app.infra.sa_models import SentencePronunciation

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

SANITIZER_VERSION = "1"

# Guard thresholds (can be overridden per-call via GuardParams)
DEFAULT_MIN_LEN = 5  # characters
DEFAULT_MAX_LEN = 2000  # characters
DEFAULT_MIN_HE_RATIO = 0.10  # fraction of Hebrew letter chars in preprocessed text

# QC thresholds
QC_OK_THRESHOLD = 0.75
QC_PARTIAL_THRESHOLD = 0.40

# Segmentation
DEFAULT_SEGMENT_MAX_CHARS = 380


# ── Hebrew helpers ──────────────────────────────────────────────────────────────


def _is_hebrew_letter(char: str) -> bool:
    """Return True if char is a Hebrew letter (U+05D0–U+05EA, U+FB1D–U+FB4E)."""
    code = ord(char)
    return (0x05D0 <= code <= 0x05EA) or (0xFB1D <= code <= 0xFB4E)


def _count_nikud(char: str) -> bool:
    """Return True if char is a Hebrew nikud (vowel) mark."""
    code = ord(char)
    _NIKUD_RANGES = [
        (0x05B0, 0x05BC),
        (0x05BD, 0x05BD),
        (0x05BF, 0x05BF),
        (0x05C1, 0x05C2),
        (0x05C4, 0x05C5),
        (0x05C7, 0x05C7),
    ]
    return any(s <= code <= e for s, e in _NIKUD_RANGES)


def compute_niqqud_coverage(niqqud_text: str) -> float:
    """Return fraction of Hebrew words that have at least one nikud mark.

    A "word" is a sequence of Hebrew letters (possibly with embedded nikud).
    Words with zero nikud marks count against coverage.
    """
    # Tokenise by whitespace into words that contain Hebrew letters
    words = niqqud_text.split()
    he_words = [w for w in words if any(_is_hebrew_letter(c) for c in w)]
    if not he_words:
        return 0.0
    words_with_nikud = sum(1 for w in he_words if any(_count_nikud(c) for c in w))
    return words_with_nikud / len(he_words)


# ── Segmenter ───────────────────────────────────────────────────────────────────

# Clause boundary pattern: split after [.,;:!?] followed by whitespace, or on newlines.
_CLAUSE_BOUNDARY_RE = re.compile(r"(?<=[.,;:!?\n])\s+|\n+")


class SentenceSegmenter:
    """Split long sentences at clause boundaries to respect model token limits."""

    def __init__(self, max_chars: int = DEFAULT_SEGMENT_MAX_CHARS):
        self.max_chars = max_chars

    def split(self, text: str) -> list[str]:
        """Return list of segments, each ≤ max_chars if possible.

        If a single clause is already longer than max_chars, it passes through
        unsplit (the generator must handle it or truncate).
        """
        if len(text) <= self.max_chars:
            return [text]

        # Try splitting on clause boundaries
        parts = _CLAUSE_BOUNDARY_RE.split(text)
        segments: list[str] = []
        current = ""

        for part in parts:
            part = part.strip()
            if not part:
                continue
            candidate = (current + " " + part).strip() if current else part
            if len(candidate) <= self.max_chars:
                current = candidate
            else:
                if current:
                    segments.append(current)
                # If the part itself is too long, add as-is (can't split further here)
                current = part

        if current:
            segments.append(current)

        return segments if segments else [text]


# ── Guard params ────────────────────────────────────────────────────────────────


@dataclass
class GuardParams:
    min_len: int = DEFAULT_MIN_LEN
    max_len: int = DEFAULT_MAX_LEN
    min_he_ratio: float = DEFAULT_MIN_HE_RATIO


# ── Service ─────────────────────────────────────────────────────────────────────


class SentencePronunciationService:
    """Core CRUD + QC for the sentence_pronunciation table."""

    SANITIZER_VERSION = SANITIZER_VERSION

    # ── Hash ──────────────────────────────────────────────────────────────────

    @staticmethod
    def compute_src_hash(
        lang: str,
        preprocessed_text: str,
        phonikud_version: str,
    ) -> str:
        """Return 32-char hex digest as idempotency key."""
        payload = json.dumps(
            {
                "lang": lang,
                "text": preprocessed_text,
                "pv": phonikud_version,
                "sv": SANITIZER_VERSION,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    # ── Text preprocessing ────────────────────────────────────────────────────

    _FORMAT_CODEPOINTS = frozenset(
        [
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
        ]
    )
    _MULTISPACE_RE = re.compile(r"[ \t]+")

    @classmethod
    def preprocess_text(cls, text: str) -> str:
        """Strip bidi/joiners, normalize whitespace; keep punctuation and numbers."""
        chars: list[str] = []
        for char in text or "":
            if ord(char) in cls._FORMAT_CODEPOINTS:
                continue
            chars.append(char)
        result = "".join(chars)
        # Normalize runs of spaces/tabs (keep single newlines for segmentation)
        result = cls._MULTISPACE_RE.sub(" ", result)
        return result.strip()

    # ── Guards ────────────────────────────────────────────────────────────────

    @staticmethod
    def should_process(
        text: str,
        *,
        guard: GuardParams | None = None,
    ) -> tuple[bool, str]:
        """Check whether a sentence should be processed.

        Returns (True, "") if ok, or (False, skip_reason) otherwise.
        """
        g = guard or GuardParams()
        if len(text) < g.min_len:
            return False, "skipped_too_short"
        if len(text) > g.max_len:
            return False, "skipped_too_long"

        total = sum(1 for c in text if unicodedata.category(c).startswith("L"))
        he_count = sum(1 for c in text if _is_hebrew_letter(c))
        if total > 0 and (he_count / total) < g.min_he_ratio:
            return False, "skipped_non_hebrew_ratio"
        if total == 0:
            return False, "skipped_non_hebrew_ratio"

        return True, ""

    # ── QC ────────────────────────────────────────────────────────────────────

    @staticmethod
    def run_qc(niqqud_text: str) -> tuple[str, str | None, float | None]:
        """Validate generated niqqud text.

        Returns (qc_status, qc_reason, niqqud_coverage).
        """
        from app.services.pronunciation_quality_service import PronunciationQualityService

        if not niqqud_text or not niqqud_text.strip():
            return "rejected", "empty_output", 0.0

        if not PronunciationQualityService.has_hebrew_nikud(niqqud_text):
            return "rejected", "no_nikud_marks", 0.0

        coverage = compute_niqqud_coverage(niqqud_text)
        if coverage >= QC_OK_THRESHOLD:
            return "ok", None, coverage
        elif coverage >= QC_PARTIAL_THRESHOLD:
            return "partial", f"coverage={coverage:.2f}", coverage
        else:
            return "rejected", f"coverage_too_low={coverage:.2f}", coverage

    # ── Upsert (auto) ─────────────────────────────────────────────────────────

    @staticmethod
    def _now_str() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def upsert_auto(
        self,
        session: Session,
        *,
        sentence_id: int,
        lang: str,
        src_hash: str,
        src_preprocessed: str,
        niqqud_text: str | None,
        confidence: float | None,
        qc_status: str,
        qc_reason: str | None,
        niqqud_coverage: float | None,
        phonikud_version: str | None,
        mode: str = "fill_only",  # "fill_only" | "rebuild"
    ) -> str:
        """Insert or update a sentence_pronunciation row (auto source).

        Returns one of: "inserted" | "updated" | "skipped_has_override" |
                        "skipped_same_hash"

        Rules:
        - is_override=1 → always skipped (manual wins).
        - fill_only: skipped if existing hash == new hash AND niqqud non-empty.
        - rebuild: updates if is_override=0 (even if same hash).
        """
        existing = session.get(SentencePronunciation, sentence_id)

        if existing is not None:
            if existing.is_override:
                return "skipped_has_override"
            if mode == "fill_only":
                if existing.src_hash == src_hash and existing.niqqud_text:
                    return "skipped_same_hash"
            else:  # rebuild
                if existing.src_hash == src_hash and existing.niqqud_text:
                    return "skipped_same_hash"

            # Update existing row
            existing.lang = lang
            existing.src_hash = src_hash
            existing.src_preprocessed = src_preprocessed
            existing.niqqud_text = niqqud_text
            existing.source = "auto_phonikud"
            existing.confidence = confidence
            existing.qc_status = qc_status
            existing.qc_reason = qc_reason
            existing.niqqud_coverage = niqqud_coverage
            existing.phonikud_version = phonikud_version
            existing.sanitizer_version = SANITIZER_VERSION
            existing.error_kind = None
            existing.error_details = None
            existing.review_status = "auto"
            existing.updated_at = self._now_str()
            return "updated"
        else:
            row = SentencePronunciation(
                sentence_id=sentence_id,
                lang=lang,
                src_hash=src_hash,
                src_preprocessed=src_preprocessed,
                niqqud_text=niqqud_text,
                source="auto_phonikud",
                is_override=0,
                confidence=confidence,
                qc_status=qc_status,
                qc_reason=qc_reason,
                niqqud_coverage=niqqud_coverage,
                phonikud_version=phonikud_version,
                sanitizer_version=SANITIZER_VERSION,
                review_status="auto",
                created_at=self._now_str(),
                updated_at=self._now_str(),
            )
            session.add(row)
            return "inserted"

    def record_error(
        self,
        session: Session,
        *,
        sentence_id: int,
        lang: str,
        src_hash: str,
        src_preprocessed: str,
        error_kind: str,
        error_details: str,
        phonikud_version: str | None,
    ) -> None:
        """Record a failed generation attempt without overwriting an override."""
        existing = session.get(SentencePronunciation, sentence_id)
        if existing is not None and existing.is_override:
            return  # Never touch overrides
        now = self._now_str()
        if existing is not None:
            existing.lang = lang
            existing.src_hash = src_hash
            existing.src_preprocessed = src_preprocessed
            existing.qc_status = "failed"
            existing.error_kind = error_kind
            existing.error_details = error_details[:500] if error_details else None
            existing.phonikud_version = phonikud_version
            existing.updated_at = now
        else:
            row = SentencePronunciation(
                sentence_id=sentence_id,
                lang=lang,
                src_hash=src_hash,
                src_preprocessed=src_preprocessed,
                niqqud_text=None,
                source="auto_phonikud",
                is_override=0,
                qc_status="failed",
                error_kind=error_kind,
                error_details=error_details[:500] if error_details else None,
                phonikud_version=phonikud_version,
                sanitizer_version=SANITIZER_VERSION,
                review_status="auto",
                created_at=now,
                updated_at=now,
            )
            session.add(row)

    # ── Upsert (manual override) ──────────────────────────────────────────────

    def upsert_manual(
        self,
        session: Session,
        *,
        sentence_id: int,
        niqqud_text: str,
        notes: str | None = None,
    ) -> None:
        """Save a manual override — sets is_override=1, source='manual'."""
        from app.services.pronunciation_quality_service import PronunciationQualityService

        clean_text = PronunciationQualityService.sanitize_tts_text(niqqud_text)
        now = self._now_str()
        existing = session.get(SentencePronunciation, sentence_id)

        if existing is not None:
            existing.niqqud_text = clean_text
            existing.source = "manual"
            existing.is_override = 1
            existing.qc_status = "ok" if clean_text else "pending"
            existing.qc_reason = notes
            existing.review_status = "approved"
            existing.error_kind = None
            existing.error_details = None
            existing.updated_at = now
        else:
            row = SentencePronunciation(
                sentence_id=sentence_id,
                lang="he",
                src_hash="manual",
                src_preprocessed=None,
                niqqud_text=clean_text,
                source="manual",
                is_override=1,
                qc_status="ok" if clean_text else "pending",
                qc_reason=notes,
                review_status="approved",
                sanitizer_version=SANITIZER_VERSION,
                created_at=now,
                updated_at=now,
            )
            session.add(row)

    # ── Clear ─────────────────────────────────────────────────────────────────

    def clear(self, session: Session, *, sentence_id: int) -> bool:
        """Clear niqqud_text; reset to pending.  Returns True if row existed."""
        existing = session.get(SentencePronunciation, sentence_id)
        if existing is None:
            return False
        existing.niqqud_text = None
        existing.is_override = 0
        existing.source = "auto_phonikud"
        existing.qc_status = "pending"
        existing.qc_reason = None
        existing.review_status = "auto"
        existing.updated_at = self._now_str()
        return True

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_effective_niqqud(
        self,
        session: Session,
        sentence_id: int,
    ) -> SentenceNiqqudOverlay | None:
        """Return the effective niqqud overlay for one sentence_id, or None."""
        row = session.get(SentencePronunciation, sentence_id)
        if row is None:
            return None
        return self._to_overlay(row)

    def bulk_get_niqqud(
        self,
        session: Session,
        sentence_ids: list[int],
    ) -> dict[int, SentenceNiqqudOverlay]:
        """Batch lookup: {sentence_id: SentenceNiqqudOverlay}.

        Only returns rows where niqqud_text is not empty (qc_status ok/partial/auto_fixed/manual).
        Rejected/failed rows are also included so the UI can show the QC badge.
        """
        if not sentence_ids:
            return {}
        stmt = select(SentencePronunciation).where(
            SentencePronunciation.sentence_id.in_(sentence_ids)
        )
        rows = session.execute(stmt).scalars().all()
        return {row.sentence_id: self._to_overlay(row) for row in rows}

    @staticmethod
    def _to_overlay(row: SentencePronunciation) -> SentenceNiqqudOverlay:
        from app.services.pronunciation_quality_service import PronunciationQualityService

        # Only serve niqqud_text if it has actual nikud marks; otherwise expose None
        # (so the UI won't show empty/plain text as if it were nikud-ized)
        text = row.niqqud_text
        if text and not PronunciationQualityService.has_hebrew_nikud(text):
            text = None
        return SentenceNiqqudOverlay(
            sentence_id=row.sentence_id,
            niqqud_text=text,
            qc_status=row.qc_status,
            qc_reason=row.qc_reason,
            source=row.source,
            confidence=row.confidence,
            niqqud_coverage=row.niqqud_coverage,
            is_override=bool(row.is_override),
            review_status=row.review_status,
        )
