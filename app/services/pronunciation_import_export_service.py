"""Import/export service for pronunciation dictionary."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Dict

from sqlalchemy import asc, select
from sqlalchemy.orm import Session

from app.infra.sa_models import PronunciationEntry
from app.services.pronunciation_service import PronunciationService

logger = logging.getLogger(__name__)


class PronunciationImportExportService:
    """CSV/TSV exchange for pronunciation metadata."""

    HEADER = ["lang", "src_norm", "niqqud_text", "ipa", "source", "is_override", "notes"]

    def __init__(self, service: PronunciationService | None = None):
        self.service = service or PronunciationService()

    def export_file(
        self,
        session: Session,
        *,
        out_path: Path,
        delimiter: str = "\t",
        include_auto: bool = True,
        include_manual: bool = True,
    ) -> Dict[str, int]:
        """Export pronunciation entries to TSV/CSV."""
        out = Path(out_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)

        stmt = select(PronunciationEntry).order_by(
            asc(PronunciationEntry.lang),
            asc(PronunciationEntry.src_norm),
        )
        rows = []
        for row in session.execute(stmt).scalars().all():
            is_manual = bool(row.is_override) or (row.source == "manual")
            if is_manual and not include_manual:
                continue
            if (not is_manual) and not include_auto:
                continue
            rows.append(row)

        with out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter=delimiter)
            writer.writerow(self.HEADER)
            for row in rows:
                writer.writerow(
                    [
                        row.lang,
                        row.src_norm,
                        row.niqqud_text or "",
                        row.ipa or "",
                        row.source,
                        int(row.is_override or 0),
                        row.notes or "",
                    ]
                )

        return {"exported": len(rows)}

    def import_file(
        self,
        session: Session,
        *,
        in_path: Path,
        delimiter: str = "\t",
        allow_auto_overwrite: bool = False,
    ) -> Dict[str, int]:
        """Import pronunciation entries from TSV/CSV with manual-wins merge."""
        file_path = Path(in_path).resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"Pronunciation file not found: {file_path}")

        processed = 0
        updated = 0
        skipped = 0
        failed = 0

        with file_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            for row in reader:
                processed += 1
                try:
                    lang = (row.get("lang") or "").strip()
                    src_norm = (row.get("src_norm") or "").strip()
                    if not lang or not src_norm:
                        skipped += 1
                        continue
                    source = (row.get("source") or "auto").strip().lower()
                    is_override = str(row.get("is_override") or "0").strip() in {"1", "true", "True"}
                    before = self.service.get_entry(session, lang=lang, src_norm=src_norm)
                    after = self.service.upsert_entry(
                        session,
                        lang=lang,
                        src_norm=src_norm,
                        niqqud_text=row.get("niqqud_text"),
                        ipa=row.get("ipa"),
                        source=source,
                        is_override=is_override,
                        notes=row.get("notes"),
                        allow_auto_overwrite=allow_auto_overwrite,
                    )
                    if before is None:
                        updated += 1
                    elif (
                        (before.niqqud_text or "") != (after.niqqud_text or "")
                        or (before.ipa or "") != (after.ipa or "")
                        or (before.notes or "") != (after.notes or "")
                        or before.source != after.source
                        or before.is_override != after.is_override
                    ):
                        updated += 1
                    else:
                        skipped += 1
                except Exception as exc:
                    logger.warning("Pronunciation import row failed: %s", exc)
                    failed += 1

        return {
            "processed": processed,
            "updated": updated,
            "skipped": skipped,
            "failed": failed,
        }
