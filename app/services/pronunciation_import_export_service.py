"""Import/export service for pronunciation dictionary."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Dict

from sqlalchemy import asc, select
from sqlalchemy.orm import Session

from app.infra.sa_models import PronunciationEntry
from app.services.pronunciation_service import PronunciationService

logger = logging.getLogger(__name__)


class PronunciationImportExportService:
    """CSV/TSV exchange for pronunciation metadata."""

    HEADER = [
        "lang",
        "src_norm",
        "niqqud_text",
        "ipa",
        "reading_text",
        "source",
        "confidence",
        "is_override",
        "notes",
    ]
    PLS_NS = "http://www.w3.org/2005/01/pronunciation-lexicon"

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
                        row.reading_text or "",
                        row.source,
                        "" if row.confidence is None else f"{float(row.confidence):.6f}".rstrip("0").rstrip("."),
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
                    source = (row.get("source") or "import_csv").strip().lower()
                    is_override = str(row.get("is_override") or "0").strip() in {"1", "true", "True"}
                    confidence_raw = (row.get("confidence") or "").strip()
                    confidence = None
                    if confidence_raw:
                        try:
                            confidence = float(confidence_raw)
                        except Exception:
                            confidence = None
                    before = self.service.get_entry(session, lang=lang, src_norm=src_norm)
                    after = self.service.upsert_entry(
                        session,
                        lang=lang,
                        src_norm=src_norm,
                        niqqud_text=row.get("niqqud_text"),
                        ipa=row.get("ipa"),
                        reading_text=row.get("reading_text"),
                        source=source,
                        confidence=confidence,
                        is_override=is_override,
                        notes=row.get("notes"),
                        allow_auto_overwrite=allow_auto_overwrite,
                    )
                    if before is None:
                        updated += 1
                    elif (
                        (before.niqqud_text or "") != (after.niqqud_text or "")
                        or (before.ipa or "") != (after.ipa or "")
                        or (before.reading_text or "") != (after.reading_text or "")
                        or (before.notes or "") != (after.notes or "")
                        or before.confidence != after.confidence
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

    def export_pls(
        self,
        session: Session,
        *,
        out_path: Path,
        lang: str,
        include_auto: bool = True,
        include_manual: bool = True,
    ) -> Dict[str, int]:
        """Export IPA pronunciation entries to PLS lexicon."""
        out = Path(out_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        lang_clean = (lang or "").strip()

        rows = session.execute(
            select(PronunciationEntry)
            .where(PronunciationEntry.lang == lang_clean)
            .order_by(asc(PronunciationEntry.src_norm))
        ).scalars().all()

        root = ET.Element("lexicon", attrib={"version": "1.0", "{http://www.w3.org/XML/1998/namespace}lang": lang_clean})
        root.set("xmlns", self.PLS_NS)
        exported = 0
        for row in rows:
            is_manual = bool(row.is_override) or (row.source == "manual")
            if is_manual and not include_manual:
                continue
            if (not is_manual) and not include_auto:
                continue
            ipa_value = (row.ipa or "").strip()
            if not ipa_value:
                continue
            lexeme = ET.SubElement(root, "lexeme")
            grapheme = ET.SubElement(lexeme, "grapheme")
            grapheme.text = row.src_norm
            phoneme = ET.SubElement(lexeme, "phoneme", attrib={"alphabet": "ipa"})
            phoneme.text = ipa_value
            exported += 1

        tree = ET.ElementTree(root)
        tree.write(out, encoding="utf-8", xml_declaration=True)
        return {"exported": exported}

    def import_pls(
        self,
        session: Session,
        *,
        in_path: Path,
        default_lang: str = "he",
        is_override: bool = False,
        allow_auto_overwrite: bool = False,
    ) -> Dict[str, int]:
        """Import PLS lexicon (IPA phoneme profile)."""
        file_path = Path(in_path).resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"PLS file not found: {file_path}")

        tree = ET.parse(file_path)
        root = tree.getroot()
        lang = (
            root.attrib.get("{http://www.w3.org/XML/1998/namespace}lang")
            or (default_lang or "").strip()
            or "he"
        )

        processed = 0
        updated = 0
        skipped = 0
        failed = 0

        for lexeme in root.findall(".//{*}lexeme"):
            processed += 1
            try:
                grapheme = (lexeme.findtext("{*}grapheme") or "").strip()
                if not grapheme:
                    skipped += 1
                    continue
                phoneme_node = None
                for node in lexeme.findall("{*}phoneme"):
                    alphabet = (node.attrib.get("alphabet") or "").strip().lower()
                    if alphabet == "ipa":
                        phoneme_node = node
                        break
                ipa = (phoneme_node.text or "").strip() if phoneme_node is not None else ""
                if not ipa:
                    skipped += 1
                    continue

                before = self.service.get_entry(session, lang=lang, src_norm=grapheme)
                after = self.service.upsert_entry(
                    session,
                    lang=lang,
                    src_norm=grapheme,
                    niqqud_text=None,
                    ipa=ipa,
                    reading_text=None,
                    source="manual" if is_override else "import_pls",
                    confidence=None,
                    is_override=is_override,
                    notes="import:pls",
                    allow_auto_overwrite=allow_auto_overwrite,
                )
                if before is None or before.ipa != after.ipa or before.source != after.source:
                    updated += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.warning("Pronunciation PLS import row failed: %s", exc)
                failed += 1

        return {
            "processed": processed,
            "updated": updated,
            "skipped": skipped,
            "failed": failed,
        }
