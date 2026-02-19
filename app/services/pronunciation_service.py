"""Pronunciation dictionary service."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

from sqlalchemy import asc, select
from sqlalchemy.orm import Session

from app.domain.dto import PronunciationEntryDTO
from app.infra.sa_models import PronunciationEntry

logger = logging.getLogger(__name__)


class PronunciationService:
    """Manage auto/manual pronunciation entries."""

    VALID_SOURCES = {"auto", "manual"}

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
        source: str,
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

        niqqud_clean = self._clean_text(niqqud_text)
        ipa_clean = self._clean_text(ipa)
        notes_clean = self._clean_text(notes)
        incoming_manual = source_key == "manual" or bool(is_override)
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
                source="manual" if incoming_manual else "auto",
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
            row.source = "manual"
            row.is_override = 1
            row.notes = notes_clean
            row.updated_at = now_str
            session.flush()
            return self._to_dto(row)

        # Auto source update.
        if allow_auto_overwrite:
            row.niqqud_text = niqqud_clean
            row.ipa = ipa_clean
            row.notes = notes_clean if notes_clean is not None else row.notes
        else:
            if not (row.niqqud_text or "").strip() and niqqud_clean:
                row.niqqud_text = niqqud_clean
            if not (row.ipa or "").strip() and ipa_clean:
                row.ipa = ipa_clean
            if not (row.notes or "").strip() and notes_clean:
                row.notes = notes_clean
        row.source = "auto"
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
                        source="auto",
                        is_override=False,
                        notes=item.get("notes"),
                        allow_auto_overwrite=rebuild_auto,
                    )
                    if dto_before is None:
                        added_or_updated += 1
                    elif (
                        (dto_before.niqqud_text or "") != (dto_after.niqqud_text or "")
                        or (dto_before.ipa or "") != (dto_after.ipa or "")
                        or (dto_before.notes or "") != (dto_after.notes or "")
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
    def _to_dto(row: PronunciationEntry) -> PronunciationEntryDTO:
        return PronunciationEntryDTO(
            entry_id=row.entry_id,
            lang=row.lang,
            src_norm=row.src_norm,
            niqqud_text=row.niqqud_text,
            ipa=row.ipa,
            source=row.source,
            is_override=row.is_override or 0,
            notes=row.notes,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
