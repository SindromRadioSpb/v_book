"""P3 Export Service.

Provides safe export of TM entries and dictionaries to CSV/JSON with:
- CSV injection protection (neutralize = + - @)
- JSON export without sanitization
- Deterministic output format
"""

import logging
import csv
import json
from typing import Optional, List
from sqlalchemy.orm import Session

from app.infra.sa_models import TMEntry, DictEntry, DictSource

logger = logging.getLogger(__name__)


class ExportService:
    """Service for exporting TM and dictionary data."""

    def sanitize_csv_cell(self, value: Optional[str]) -> str:
        """Sanitize cell value for CSV export to prevent injection.

        CSV injection rule:
        If value starts with = + - @ then prefix with single quote '

        Args:
            value: Cell value

        Returns:
            Sanitized value
        """
        if not value:
            return ""

        value_str = str(value)

        # Check if starts with dangerous characters
        if value_str and value_str[0] in ("=", "+", "-", "@"):
            return f"'{value_str}"

        return value_str

    def export_tm_csv(
        self,
        session: Session,
        path: str,
        *,
        project_id: Optional[int] = None,
        include_draft: bool = False,
    ) -> int:
        """Export TM entries to CSV.

        Args:
            session: Database session
            path: Output CSV file path
            project_id: Project ID (None for all)
            include_draft: Include draft entries

        Returns:
            Number of entries exported
        """
        # Build query
        query = session.query(TMEntry)

        if project_id is not None:
            query = query.filter(TMEntry.project_id == project_id)

        if not include_draft:
            query = query.filter(TMEntry.status.in_(["approved", "rejected", "deprecated"]))

        entries = query.all()

        # Export to CSV with injection protection
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)

            # Write header
            writer.writerow([
                "tm_id",
                "project_id",
                "kind",
                "src_lang",
                "tgt_lang",
                "src_text",
                "src_norm",
                "translation",
                "translation_norm",
                "pos",
                "domain",
                "notes",
                "status",
                "confidence",
                "origin",
                "source_ref",
                "created_at",
                "updated_at",
                "approved_at",
                "approved_by",
            ])

            # Write rows with sanitization
            for entry in entries:
                writer.writerow([
                    entry.tm_id,
                    entry.project_id if entry.project_id is not None else "",
                    self.sanitize_csv_cell(entry.kind),
                    self.sanitize_csv_cell(entry.src_lang),
                    self.sanitize_csv_cell(entry.tgt_lang),
                    self.sanitize_csv_cell(entry.src_text),
                    self.sanitize_csv_cell(entry.src_norm),
                    self.sanitize_csv_cell(entry.translation),
                    self.sanitize_csv_cell(entry.translation_norm),
                    self.sanitize_csv_cell(entry.pos),
                    self.sanitize_csv_cell(entry.domain),
                    self.sanitize_csv_cell(entry.notes),
                    self.sanitize_csv_cell(entry.status),
                    entry.confidence if entry.confidence is not None else "",
                    self.sanitize_csv_cell(entry.origin),
                    self.sanitize_csv_cell(entry.source_ref),
                    str(entry.created_at),
                    str(entry.updated_at),
                    str(entry.approved_at) if entry.approved_at else "",
                    self.sanitize_csv_cell(entry.approved_by),
                ])

        logger.info(f"Exported {len(entries)} TM entries to {path}")
        return len(entries)

    def export_tm_json(
        self,
        session: Session,
        path: str,
        *,
        project_id: Optional[int] = None,
        include_draft: bool = False,
    ) -> int:
        """Export TM entries to JSON.

        No sanitization for JSON (only CSV needs it).

        Args:
            session: Database session
            path: Output JSON file path
            project_id: Project ID (None for all)
            include_draft: Include draft entries

        Returns:
            Number of entries exported
        """
        # Build query
        query = session.query(TMEntry)

        if project_id is not None:
            query = query.filter(TMEntry.project_id == project_id)

        if not include_draft:
            query = query.filter(TMEntry.status.in_(["approved", "rejected", "deprecated"]))

        entries = query.all()

        # Export to JSON (no sanitization needed)
        data = []
        for entry in entries:
            data.append({
                "tm_id": entry.tm_id,
                "project_id": entry.project_id,
                "kind": entry.kind,
                "src_lang": entry.src_lang,
                "tgt_lang": entry.tgt_lang,
                "src_text": entry.src_text,
                "src_norm": entry.src_norm,
                "translation": entry.translation,
                "translation_norm": entry.translation_norm,
                "pos": entry.pos,
                "domain": entry.domain,
                "notes": entry.notes,
                "status": entry.status,
                "confidence": entry.confidence,
                "origin": entry.origin,
                "source_ref": entry.source_ref,
                "created_at": str(entry.created_at),
                "updated_at": str(entry.updated_at),
                "approved_at": str(entry.approved_at) if entry.approved_at else None,
                "approved_by": entry.approved_by,
            })

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"Exported {len(entries)} TM entries to {path}")
        return len(entries)

    def export_dict_csv(
        self,
        session: Session,
        path: str,
        *,
        dict_source_id: Optional[int] = None,
        project_id: Optional[int] = None,
    ) -> int:
        """Export dictionary entries to CSV.

        Args:
            session: Database session
            path: Output CSV file path
            dict_source_id: Dict source ID (optional)
            project_id: Project ID (optional, for filtering by project scope)

        Returns:
            Number of entries exported
        """
        # Build query
        query = session.query(DictEntry)

        if dict_source_id is not None:
            query = query.filter(DictEntry.dict_source_id == dict_source_id)
        elif project_id is not None:
            # Filter by project via dict_source
            query = query.join(DictSource).filter(DictSource.project_id == project_id)

        entries = query.all()

        # Export to CSV with injection protection
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)

            # Write header
            writer.writerow([
                "dict_entry_id",
                "dict_source_id",
                "kind",
                "src_lang",
                "tgt_lang",
                "src_text",
                "src_norm",
                "translation",
                "translation_norm",
                "pos",
                "domain",
                "status",
                "priority",
                "notes",
            ])

            # Write rows with sanitization
            for entry in entries:
                writer.writerow([
                    entry.dict_entry_id,
                    entry.dict_source_id,
                    self.sanitize_csv_cell(entry.kind),
                    self.sanitize_csv_cell(entry.src_lang),
                    self.sanitize_csv_cell(entry.tgt_lang),
                    self.sanitize_csv_cell(entry.src_text),
                    self.sanitize_csv_cell(entry.src_norm),
                    self.sanitize_csv_cell(entry.translation),
                    self.sanitize_csv_cell(entry.translation_norm),
                    self.sanitize_csv_cell(entry.pos),
                    self.sanitize_csv_cell(entry.domain),
                    self.sanitize_csv_cell(entry.status),
                    entry.priority if entry.priority is not None else "",
                    self.sanitize_csv_cell(entry.notes),
                ])

        logger.info(f"Exported {len(entries)} dict entries to {path}")
        return len(entries)
