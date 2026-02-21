"""Pronunciation dictionary service."""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

from sqlalchemy import asc, select
from sqlalchemy.orm import Session

from app.domain.normalization.normalizer import normalize_for_tm
from app.domain.dto import PronunciationEntryDTO
from app.infra.sa_models import PronunciationEntry
from app.services.pronunciation_quality_service import PronunciationQualityService

logger = logging.getLogger(__name__)


@dataclass
class PronunciationApplied:
    """Prepared pronunciation payload for audio generation."""

    text: str
    token_text: str
    ssml: str
    mode: str
    is_valid: bool = True
    qc_flag: Optional[str] = None


class PronunciationService:
    """Manage auto/manual pronunciation entries."""

    VALID_SOURCES = {"manual", "auto", "auto_phonikud", "import_csv", "import_pls"}

    @staticmethod
    def _now_str() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    @staticmethod
    def _clean_text(value: Optional[str]) -> Optional[str]:
        text = (value or "").strip()
        return text or None

    def get_entry(self, session: Session, *, lang: str, src_norm: str) -> Optional[PronunciationEntryDTO]:
        """Get one pronunciation entry by `(lang, src_norm)`."""
        lang_clean = (lang or "").strip()
        norm_clean = (src_norm or "").strip()
        if not lang_clean or not norm_clean:
            return None
        row = session.execute(
            select(PronunciationEntry).where(
                PronunciationEntry.lang == lang_clean,
                PronunciationEntry.src_norm == norm_clean,
            )
        ).scalar_one_or_none()
        return self._to_dto(row) if row else None

    def bulk_lookup(
        self,
        session: Session,
        *,
        lang: str,
        src_norms: Iterable[str],
    ) -> Dict[str, PronunciationEntryDTO]:
        """Batch lookup for page overlays / generation preprocessing."""
        lang_clean = (lang or "").strip()
        norm_list = sorted({(n or "").strip() for n in src_norms if (n or "").strip()})
        if not lang_clean or not norm_list:
            return {}
        rows = session.execute(
            select(PronunciationEntry)
            .where(
                PronunciationEntry.lang == lang_clean,
                PronunciationEntry.src_norm.in_(norm_list),
            )
            .order_by(asc(PronunciationEntry.src_norm))
        ).scalars().all()
        return {row.src_norm: self._to_dto(row) for row in rows}

    def upsert_entry(
        self,
        session: Session,
        *,
        lang: str,
        src_norm: str,
        niqqud_text: Optional[str],
        ipa: Optional[str],
        reading_text: Optional[str] = None,
        source: str,
        confidence: Optional[float] = None,
        is_override: bool = False,
        notes: Optional[str] = None,
        allow_auto_overwrite: bool = False,
    ) -> PronunciationEntryDTO:
        """Upsert with manual-over-auto merge policy."""
        lang_clean = (lang or "").strip()
        norm_clean = (src_norm or "").strip()
        if not lang_clean or not norm_clean:
            raise ValueError("lang and src_norm are required")

        source_key = (source or "").strip().lower()
        if source_key not in self.VALID_SOURCES:
            raise ValueError(f"Unsupported pronunciation source: {source}")

        incoming_manual = source_key == "manual" or bool(is_override)
        niqqud_result = PronunciationQualityService.normalize_field(
            niqqud_text,
            strict=incoming_manual,
        )
        reading_result = PronunciationQualityService.normalize_field(
            reading_text,
            strict=incoming_manual,
        )
        if incoming_manual and (not niqqud_result.is_valid or not reading_result.is_valid):
            invalid_reason = niqqud_result.reason or reading_result.reason or "Invalid pronunciation payload."
            raise ValueError(invalid_reason)

        niqqud_clean = niqqud_result.value
        ipa_clean = self._clean_text(ipa)
        reading_clean = reading_result.value
        notes_clean = self._clean_text(notes)
        qc_tags: List[str] = []
        if niqqud_result.qc_flag:
            qc_tags.append(f"niqqud_{niqqud_result.qc_flag}")
        if reading_result.qc_flag:
            qc_tags.append(f"reading_{reading_result.qc_flag}")
        if qc_tags and source_key != "manual":
            qc_note = "qc:" + ",".join(sorted(set(qc_tags)))
            if notes_clean:
                if qc_note not in notes_clean:
                    notes_clean = f"{notes_clean}; {qc_note}"
            else:
                notes_clean = qc_note

        confidence_clean = float(confidence) if confidence is not None else None
        if confidence_clean is not None:
            confidence_clean = max(0.0, min(1.0, confidence_clean))
        now_str = self._now_str()

        row = session.execute(
            select(PronunciationEntry).where(
                PronunciationEntry.lang == lang_clean,
                PronunciationEntry.src_norm == norm_clean,
            )
        ).scalar_one_or_none()

        if row is None:
            row = PronunciationEntry(
                lang=lang_clean,
                src_norm=norm_clean,
                niqqud_text=niqqud_clean,
                ipa=ipa_clean,
                reading_text=reading_clean,
                source="manual" if incoming_manual else source_key,
                confidence=confidence_clean,
                is_override=1 if incoming_manual else 0,
                notes=notes_clean,
                created_at=now_str,
                updated_at=now_str,
            )
            session.add(row)
            session.flush()
            return self._to_dto(row)

        existing_manual = bool(row.is_override) or (row.source == "manual")
        if existing_manual and not incoming_manual:
            # Manual entry always wins over incoming auto data.
            return self._to_dto(row)

        if incoming_manual:
            row.niqqud_text = niqqud_clean
            row.ipa = ipa_clean
            row.reading_text = reading_clean
            row.source = "manual"
            row.confidence = confidence_clean
            row.is_override = 1
            row.notes = notes_clean
            row.updated_at = now_str
            session.flush()
            return self._to_dto(row)

        # Auto source update.
        if allow_auto_overwrite:
            row.niqqud_text = niqqud_clean
            row.ipa = ipa_clean
            row.reading_text = reading_clean
            row.confidence = confidence_clean
            row.notes = notes_clean if notes_clean is not None else row.notes
        else:
            existing_niqqud = (row.niqqud_text or "").strip()
            can_refresh_auto_niqqud = (
                not existing_niqqud
                or (
                    not existing_manual
                    and not PronunciationQualityService.has_hebrew_nikud(existing_niqqud)
                )
            )
            if can_refresh_auto_niqqud and niqqud_clean:
                row.niqqud_text = niqqud_clean
            if not (row.ipa or "").strip() and ipa_clean:
                row.ipa = ipa_clean
            if not (row.reading_text or "").strip() and reading_clean:
                row.reading_text = reading_clean
            if row.confidence is None and confidence_clean is not None:
                row.confidence = confidence_clean
            if not (row.notes or "").strip() and notes_clean:
                row.notes = notes_clean
        row.source = source_key
        row.is_override = 0
        row.updated_at = now_str
        session.flush()
        return self._to_dto(row)

    def delete_entry(self, session: Session, *, lang: str, src_norm: str) -> bool:
        """Delete entry by `(lang, src_norm)`."""
        lang_clean = (lang or "").strip()
        norm_clean = (src_norm or "").strip()
        if not lang_clean or not norm_clean:
            return False
        row = session.execute(
            select(PronunciationEntry).where(
                PronunciationEntry.lang == lang_clean,
                PronunciationEntry.src_norm == norm_clean,
            )
        ).scalar_one_or_none()
        if not row:
            return False
        session.delete(row)
        session.flush()
        return True

    def bulk_upsert_auto(
        self,
        session: Session,
        *,
        lang: str,
        entries: Iterable[Dict[str, Any]],
        chunk_size: int = 500,
        rebuild_auto: bool = False,
        source: str = "auto",
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, int]:
        """Bulk auto upsert (idempotent, manual entries remain authoritative)."""
        payload = list(entries or [])
        total = len(payload)
        processed = 0
        added_or_updated = 0
        skipped = 0
        failed = 0
        cancelled = False
        pending = 0

        for item in payload:
            if cancel_check and cancel_check():
                cancelled = True
                break
            try:
                src_norm = (item.get("src_norm") or "").strip()
                if not src_norm:
                    skipped += 1
                else:
                    dto_before = self.get_entry(session, lang=lang, src_norm=src_norm)
                    dto_after = self.upsert_entry(
                        session,
                        lang=lang,
                        src_norm=src_norm,
                        niqqud_text=item.get("niqqud_text"),
                        ipa=item.get("ipa"),
                        reading_text=item.get("reading_text"),
                        source=source,
                        confidence=item.get("confidence"),
                        is_override=False,
                        notes=item.get("notes"),
                        allow_auto_overwrite=rebuild_auto,
                    )
                    if dto_before is None:
                        added_or_updated += 1
                    elif (
                        (dto_before.niqqud_text or "") != (dto_after.niqqud_text or "")
                        or (dto_before.ipa or "") != (dto_after.ipa or "")
                        or (dto_before.reading_text or "") != (dto_after.reading_text or "")
                        or (dto_before.notes or "") != (dto_after.notes or "")
                        or dto_before.confidence != dto_after.confidence
                        or dto_before.source != dto_after.source
                        or dto_before.is_override != dto_after.is_override
                    ):
                        added_or_updated += 1
                    else:
                        skipped += 1

                pending += 1
                if pending >= max(1, int(chunk_size)):
                    session.flush()
                    pending = 0
            except Exception as exc:
                logger.warning("Failed pronunciation auto upsert: %s", exc)
                failed += 1
            finally:
                processed += 1
                if progress_callback:
                    progress_callback(processed, total)

        if pending:
            session.flush()

        return {
            "total": total,
            "processed": processed,
            "updated": added_or_updated,
            "skipped": skipped,
            "failed": failed,
            "cancelled": cancelled,
        }

    @staticmethod
    def _build_ssml_text(text_value: str) -> str:
        safe_text = PronunciationQualityService.sanitize_tts_text(text_value)
        escaped = html.escape(safe_text, quote=False)
        return f"<speak version='1.0'>{escaped}</speak>"

    @staticmethod
    def _build_ssml_ipa(surface_text: str, ipa_value: str) -> str:
        safe_surface = PronunciationQualityService.sanitize_tts_text(surface_text)
        escaped_surface = html.escape(safe_surface, quote=False)
        escaped_ipa = html.escape(ipa_value or "", quote=True)
        return (
            "<speak version='1.0'>"
            f"<phoneme alphabet='ipa' ph='{escaped_ipa}'>{escaped_surface}</phoneme>"
            "</speak>"
        )

    @staticmethod
    def _tokenize_text(text: str) -> List[str]:
        return re.findall(r"\w+|[^\w]+", text or "", flags=re.UNICODE)

    @staticmethod
    def _entry_text(entry: Optional[PronunciationEntryDTO]) -> Optional[str]:
        if not entry:
            return None
        raw = (entry.niqqud_text or "").strip() or (entry.reading_text or "").strip()
        if not raw:
            return None
        sanitized = PronunciationQualityService.sanitize_tts_text(raw)
        return sanitized or None

    def _normalize_surface(self, src_lang: str, value: str) -> str:
        return normalize_for_tm(src_lang, value, "surface").norm

    def _apply_token_pronunciation_text(
        self,
        session: Session,
        *,
        src_lang: str,
        source_text: str,
    ) -> str:
        parts = self._tokenize_text(source_text)
        if not parts:
            return source_text
        token_norms: Dict[str, str] = {}
        for part in parts:
            if not part or not part.strip() or not any(ch.isalnum() for ch in part):
                continue
            norm = self._normalize_surface(src_lang, part)
            if norm:
                token_norms[part] = norm
        if not token_norms:
            return source_text

        entries = self.bulk_lookup(
            session=session,
            lang=src_lang,
            src_norms=list(token_norms.values()),
        )
        if not entries:
            return source_text

        result_parts: List[str] = []
        changed = False
        for part in parts:
            norm = token_norms.get(part)
            if not norm:
                result_parts.append(part)
                continue
            replacement = self._entry_text(entries.get(norm))
            if replacement:
                result_parts.append(replacement)
                if replacement != part:
                    changed = True
            else:
                result_parts.append(part)
        return "".join(result_parts) if changed else source_text

    def _apply_phrase_pronunciation_text(
        self,
        session: Session,
        *,
        src_lang: str,
        source_text: str,
    ) -> str:
        parts = self._tokenize_text(source_text)
        word_part_indexes = [idx for idx, part in enumerate(parts) if part.strip() and any(ch.isalnum() for ch in part)]
        if len(word_part_indexes) < 2:
            return source_text

        words = [parts[idx] for idx in word_part_indexes]
        word_norms = [self._normalize_surface(src_lang, token) for token in words]
        if not all(word_norms):
            return source_text

        phrase_norms: set[str] = set()
        word_count = len(word_norms)
        for start in range(word_count):
            for size in range(2, (word_count - start) + 1):
                phrase_norms.add(" ".join(word_norms[start : start + size]))
        if not phrase_norms:
            return source_text

        entries = self.bulk_lookup(
            session=session,
            lang=src_lang,
            src_norms=phrase_norms,
        )
        if not entries:
            return source_text

        matches: Dict[int, tuple[int, str]] = {}
        idx = 0
        while idx < word_count:
            found = False
            for size in range(word_count - idx, 1, -1):
                key = " ".join(word_norms[idx : idx + size])
                replacement = self._entry_text(entries.get(key))
                if replacement:
                    matches[idx] = (idx + size - 1, replacement)
                    idx += size
                    found = True
                    break
            if not found:
                idx += 1
        if not matches:
            return source_text

        start_by_part_idx: Dict[int, tuple[int, str]] = {}
        for start_word, (end_word, replacement) in matches.items():
            start_part = word_part_indexes[start_word]
            end_part = word_part_indexes[end_word]
            start_by_part_idx[start_part] = (end_part, replacement)

        result_parts: List[str] = []
        skip_until = -1
        for part_idx, part in enumerate(parts):
            if part_idx <= skip_until:
                continue
            matched = start_by_part_idx.get(part_idx)
            if matched:
                end_part, replacement = matched
                result_parts.append(replacement)
                skip_until = end_part
                continue
            result_parts.append(part)
        combined = "".join(result_parts)
        return combined if combined else source_text

    def apply_to_text(
        self,
        session: Session,
        *,
        src_lang: str,
        source_text: str,
        source_norm: Optional[str] = None,
    ) -> PronunciationApplied:
        """Apply phrase-first pronunciation rules (whole phrase -> phrase map -> token fallback)."""
        src_lang_clean = (src_lang or "").strip()
        source_text_clean = (source_text or "").strip()
        source_spoken = PronunciationQualityService.sanitize_tts_text(source_text_clean)
        source_qc_flag = "auto_fixed" if source_spoken != source_text_clean else None
        if not src_lang_clean or not source_spoken:
            return PronunciationApplied(
                text=source_spoken,
                token_text=source_spoken,
                ssml="",
                mode="none",
                is_valid=bool(source_spoken),
                qc_flag=source_qc_flag,
            )

        source_norm_clean = (source_norm or "").strip() or self._normalize_surface(src_lang_clean, source_spoken)
        exact_entry = self.get_entry(
            session,
            lang=src_lang_clean,
            src_norm=source_norm_clean,
        )

        if exact_entry and (exact_entry.ipa or "").strip():
            return PronunciationApplied(
                text=source_spoken,
                token_text=source_spoken,
                ssml=self._build_ssml_ipa(source_spoken, exact_entry.ipa or ""),
                mode="exact_ipa",
                is_valid=True,
                qc_flag=source_qc_flag,
            )

        exact_text = self._entry_text(exact_entry)
        if exact_text:
            return PronunciationApplied(
                text=exact_text,
                token_text=exact_text,
                ssml=self._build_ssml_text(exact_text),
                mode="exact_text",
                is_valid=True,
                qc_flag=source_qc_flag,
            )

        phrase_text = self._apply_phrase_pronunciation_text(
            session,
            src_lang=src_lang_clean,
            source_text=source_spoken,
        )
        phrase_text = PronunciationQualityService.sanitize_tts_text(phrase_text)
        token_text = self._apply_token_pronunciation_text(
            session,
            src_lang=src_lang_clean,
            source_text=phrase_text,
        )
        token_text = PronunciationQualityService.sanitize_tts_text(token_text)
        if token_text != source_spoken:
            return PronunciationApplied(
                text=source_spoken,
                token_text=token_text,
                ssml=self._build_ssml_text(token_text),
                mode="phrase_or_token",
                is_valid=True,
                qc_flag=source_qc_flag,
            )
        mode = "source_sanitized" if source_qc_flag else "none"
        return PronunciationApplied(
            text=source_spoken,
            token_text=source_spoken,
            ssml="",
            mode=mode,
            is_valid=True,
            qc_flag=source_qc_flag,
        )

    @staticmethod
    def _to_dto(row: PronunciationEntry) -> PronunciationEntryDTO:
        return PronunciationEntryDTO(
            entry_id=row.entry_id,
            lang=row.lang,
            src_norm=row.src_norm,
            niqqud_text=row.niqqud_text,
            ipa=row.ipa,
            reading_text=row.reading_text,
            source=row.source,
            confidence=row.confidence,
            is_override=row.is_override or 0,
            notes=row.notes,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
