"""P3 Export Service + M9 XLSX/TBX/TMX.

Provides safe export of TM entries and dictionaries to multiple formats:
- CSV/JSON: CSV injection protection (neutralize = + - @)
- XLSX: Multi-sheet export (Dictionary + Statistics) via openpyxl
- TBX: TermBase eXchange XML format
- TMX: Translation Memory eXchange XML format
- Atomic file writing (temp + replace)
"""

import logging
import csv
import json
import os
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional, List, BinaryIO
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.infra.sa_models import (
    TMEntry, DictEntry, DictSource, TermCluster,
    Lemma, DictProject, SourceDocument
)
from app.services.stats_service import StatsService

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

    # ========================================================================
    # M9: XLSX Export (Multi-Sheet)
    # ========================================================================

    def export_xlsx(
        self,
        session: Session,
        path: str,
        *,
        project_id: int,
    ) -> int:
        """Export project data to Excel workbook with multiple sheets.

        Creates an XLSX file with:
        - Sheet "Dictionary": Source/Translation pairs from TM + Dict
        - Sheet "Statistics": Project-level aggregate statistics

        Args:
            session: Database session
            path: Output XLSX file path
            project_id: Project ID to export

        Returns:
            Number of dictionary entries exported

        Note: Uses atomic file writing (temp + replace)
        """
        try:
            import openpyxl
            from openpyxl.styles import Font, Alignment
        except ImportError:
            raise ImportError("openpyxl is required for XLSX export. Install: pip install openpyxl")

        def write_xlsx(f: BinaryIO):
            """Write XLSX content to file handle."""
            wb = openpyxl.Workbook()

            # Remove default sheet
            wb.remove(wb.active)

            # ================================================================
            # Sheet 1: Dictionary
            # ================================================================
            ws_dict = wb.create_sheet("Dictionary", 0)

            # Headers
            headers = [
                "Source (Hebrew)", "Translation (Russian)", "Status",
                "Origin", "Kind", "Frequency", "Notes"
            ]

            ws_dict.append(headers)

            # Style headers
            for cell in ws_dict[1]:
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal="left")

            # Get TM entries
            tm_entries = (
                session.query(TMEntry)
                .filter(TMEntry.project_id == project_id)
                .order_by(TMEntry.src_text)
                .all()
            )

            row_count = 0
            for entry in tm_entries:
                ws_dict.append([
                    entry.src_text or "",
                    entry.translation or "",
                    entry.status or "",
                    entry.origin or "",
                    entry.kind or "",
                    "",  # Frequency (not available for TM entries)
                    entry.notes or "",
                ])
                row_count += 1

            # Skip dict entries for now (dict_source table may not exist in all schemas)
            # Get lemmas with translations
            lemmas = (
                session.query(Lemma)
                .filter(Lemma.project_id == project_id)
                .order_by(Lemma.lemma_text)
                .limit(100)  # Limit to avoid huge exports
                .all()
            )

            # For lemmas, try to get translation from TM and frequency from stats
            for lemma in lemmas:
                # Look up translation in TM
                tm_entry = (
                    session.query(TMEntry)
                    .filter(
                        TMEntry.project_id == project_id,
                        TMEntry.kind == "lemma",
                        TMEntry.src_text == lemma.lemma_text,
                    )
                    .first()
                )

                # Look up frequency from LemmaProjectStat
                from app.infra.sa_models import LemmaProjectStat
                lemma_stat = (
                    session.query(LemmaProjectStat)
                    .filter(
                        LemmaProjectStat.project_id == project_id,
                        LemmaProjectStat.lemma_id == lemma.lemma_id,
                    )
                    .first()
                )

                translation = tm_entry.translation if tm_entry else ""
                status = tm_entry.status if tm_entry else "untranslated"
                frequency = lemma_stat.freq_abs if lemma_stat else ""

                ws_dict.append([
                    lemma.lemma_text or "",
                    translation,
                    status,
                    "lemma",
                    lemma.pos or "",
                    frequency,
                    "",
                ])
                row_count += 1

            # Auto-size columns
            for column in ws_dict.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                ws_dict.column_dimensions[column_letter].width = adjusted_width

            # ================================================================
            # Sheet 2: Statistics
            # ================================================================
            ws_stats = wb.create_sheet("Statistics", 1)

            ws_stats.append(["Metric", "Value"])

            # Style header
            for cell in ws_stats[1]:
                cell.font = Font(bold=True)

            # Compute project statistics using StatsService
            stats_service = StatsService()
            stats = stats_service.compute_project_stats(session, project_id)

            # Get metrics registry for deterministic ordering
            from app.services.metrics_registry import get_registry, MetricType
            registry = get_registry()

            # Convert stats dataclass to dict for lookups
            stats_dict = {
                "project_name": stats.project_name,
                "project_id": stats.project_id,
                "document_count": stats.document_count,
                "lemma_count": stats.lemma_count,
                "lemmas_with_translation_count": stats.lemmas_with_translation_count,
                "term_cluster_count": stats.term_cluster_count,
                "term_approved_count": stats.term_approved_count,
                "tm_entry_count": stats.tm_entry_count,
                "tm_approved_count": stats.tm_approved_count,
                "dict_entry_count": stats.dict_entry_count,
                "lemma_coverage_pct": stats.lemma_coverage_pct,
                "tm_approval_rate_pct": stats.tm_approval_rate_pct,
                "term_approval_rate_pct": stats.term_approval_rate_pct,
                "tm_entries_per_lemma_pct": stats.tm_entries_per_lemma_pct,
            }

            # Write statistics rows in registry-defined order
            for spec in registry.get_ordered_specs():
                if spec.type == MetricType.SEPARATOR:
                    ws_stats.append(["", ""])
                else:
                    value = stats_dict.get(spec.key)
                    if value is None:
                        continue  # Skip if not in stats

                    # Format value based on type
                    if spec.type == MetricType.TEXT:
                        formatted_value = str(value)
                    elif spec.type == MetricType.COUNT:
                        formatted_value = int(value)
                    elif spec.type in (MetricType.RATE_0_100, MetricType.DENSITY):
                        formatted_value = f"{value:.1f}%"
                    else:
                        formatted_value = str(value)

                    ws_stats.append([spec.label, formatted_value])

            # Auto-size columns
            ws_stats.column_dimensions['A'].width = 30
            ws_stats.column_dimensions['B'].width = 20

            # Write to file handle
            wb.save(f)

            return row_count  # Return from inner function

        # Atomic write
        result = self._atomic_write_with_result(path, write_xlsx)

        logger.info(f"Exported XLSX to {path} ({result} dictionary entries, 2 sheets)")
        return result

    def _atomic_write(self, target_path: str, write_func):
        """Atomic file write: write to temp, then replace.

        Args:
            target_path: Target file path
            write_func: Function(file_handle) that writes content
        """
        dir_path = os.path.dirname(target_path) or "."
        fd, temp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")

        try:
            with os.fdopen(fd, 'wb') as f:
                write_func(f)

            # Atomic replace (works on Windows and POSIX)
            os.replace(temp_path, target_path)

        except Exception as e:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except:
                pass
            raise e

    def _atomic_write_with_result(self, target_path: str, write_func):
        """Atomic file write with return value: write to temp, then replace.

        Args:
            target_path: Target file path
            write_func: Function(file_handle) that writes content and returns a value

        Returns:
            Value returned by write_func
        """
        dir_path = os.path.dirname(target_path) or "."
        fd, temp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")

        try:
            with os.fdopen(fd, 'wb') as f:
                result = write_func(f)

            # Atomic replace (works on Windows and POSIX)
            os.replace(temp_path, target_path)

            return result

        except Exception as e:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except:
                pass
            raise e

    # ========================================================================
    # M9: TBX Export (TermBase eXchange)
    # ========================================================================

    def export_tbx(
        self,
        session: Session,
        path: str,
        *,
        project_id: int,
        approved_only: bool = True,
        include_pinned: bool = True,
    ) -> int:
        """Export term clusters to TBX (TermBase eXchange) XML format.

        Args:
            session: Database session
            path: Output TBX file path
            project_id: Project ID to export
            approved_only: Export only approved terms (default True)
            include_pinned: Include pinned translations (default True)

        Returns:
            Number of term entries exported

        Note: Uses language codes he/ru (ISO 639-1)
        """
        # Query term clusters
        query = session.query(TermCluster).filter(TermCluster.project_id == project_id)

        if approved_only:
            query = query.filter(TermCluster.curation_status == "approved")

        # Stable order for determinism
        query = query.order_by(TermCluster.canonical_key, TermCluster.cluster_id)
        clusters = query.all()

        # Build TBX XML
        def write_tbx(f: BinaryIO):
            # Root element
            tbx = ET.Element("tbx", {
                "type": "TBX-Basic",
                "style": "dca",
                "xml:lang": "he"
            })

            # Text element
            text = ET.SubElement(tbx, "text")
            body = ET.SubElement(text, "body")

            count = 0
            for cluster in clusters:
                # Create termEntry for each cluster
                term_entry = ET.SubElement(body, "termEntry", {"id": f"c{cluster.cluster_id}"})

                # Hebrew langSet
                langset_he = ET.SubElement(term_entry, "langSet", {"xml:lang": "he"})
                tig_he = ET.SubElement(langset_he, "tig")
                term_he = ET.SubElement(tig_he, "term")
                term_he.text = self._sanitize_xml_text(cluster.representative_he)

                # Russian langSet (if translation exists)
                translation = None
                if include_pinned and cluster.pinned_translation:
                    translation = cluster.pinned_translation

                if translation:
                    langset_ru = ET.SubElement(term_entry, "langSet", {"xml:lang": "ru"})
                    tig_ru = ET.SubElement(langset_ru, "tig")
                    term_ru = ET.SubElement(tig_ru, "term")
                    term_ru.text = self._sanitize_xml_text(translation)

                count += 1

            # Write to file
            tree = ET.ElementTree(tbx)
            ET.indent(tree, space="  ")  # Pretty print
            tree.write(f, encoding="utf-8", xml_declaration=True)

            return count

        # Atomic write
        result = self._atomic_write_with_result(path, write_tbx)

        logger.info(f"Exported TBX to {path} ({result} term entries)")
        return result

    # ========================================================================
    # M9: TMX Export (Translation Memory eXchange)
    # ========================================================================

    def export_tmx(
        self,
        session: Session,
        path: str,
        *,
        project_id: int,
        include_draft: bool = False,
        include_pinned: bool = True,
    ) -> int:
        """Export TM entries to TMX (Translation Memory eXchange) XML format.

        Args:
            session: Database session
            path: Output TMX file path
            project_id: Project ID to export
            include_draft: Include draft status entries (default False)
            include_pinned: Include pinned translations from term clusters (default True)

        Returns:
            Number of translation units exported

        Note: Uses language codes he/ru (ISO 639-1)
        """
        # Query TM entries
        query = session.query(TMEntry).filter(TMEntry.project_id == project_id)

        if not include_draft:
            query = query.filter(TMEntry.status.in_(["approved", "rejected", "deprecated"]))

        # Stable order for determinism
        query = query.order_by(TMEntry.src_text, TMEntry.tm_id)
        tm_entries = query.all()

        # Get pinned translations from term clusters if requested
        pinned_entries = []
        if include_pinned:
            clusters_with_pinned = (
                session.query(TermCluster)
                .filter(
                    TermCluster.project_id == project_id,
                    TermCluster.pinned_translation.isnot(None)
                )
                .order_by(TermCluster.representative_he)
                .all()
            )
            pinned_entries = [(c.representative_he, c.pinned_translation) for c in clusters_with_pinned]

        # Build TMX XML
        def write_tmx(f: BinaryIO):
            # Root element
            tmx = ET.Element("tmx", {"version": "1.4"})

            # Header
            header = ET.SubElement(tmx, "header", {
                "creationtool": "V_book",
                "creationtoolversion": "1.0",
                "datatype": "plaintext",
                "segtype": "sentence",
                "adminlang": "en",
                "srclang": "he",
                "o-tmf": "unknown"
            })

            # Body
            body = ET.SubElement(tmx, "body")

            count = 0

            # Add TM entries
            for entry in tm_entries:
                tu = ET.SubElement(body, "tu")

                # Source (Hebrew)
                tuv_he = ET.SubElement(tu, "tuv", {"xml:lang": "he"})
                seg_he = ET.SubElement(tuv_he, "seg")
                seg_he.text = self._sanitize_xml_text(entry.src_text)

                # Target (Russian)
                if entry.translation:
                    tuv_ru = ET.SubElement(tu, "tuv", {"xml:lang": "ru"})
                    seg_ru = ET.SubElement(tuv_ru, "seg")
                    seg_ru.text = self._sanitize_xml_text(entry.translation)

                count += 1

            # Add pinned translations as separate TUs with prop
            for src_he, trans_ru in pinned_entries:
                tu = ET.SubElement(body, "tu")

                # Add property to mark as pinned
                prop = ET.SubElement(tu, "prop", {"type": "source"})
                prop.text = "pinned"

                # Source (Hebrew)
                tuv_he = ET.SubElement(tu, "tuv", {"xml:lang": "he"})
                seg_he = ET.SubElement(tuv_he, "seg")
                seg_he.text = self._sanitize_xml_text(src_he)

                # Target (Russian)
                tuv_ru = ET.SubElement(tu, "tuv", {"xml:lang": "ru"})
                seg_ru = ET.SubElement(tuv_ru, "seg")
                seg_ru.text = self._sanitize_xml_text(trans_ru)

                count += 1

            # Write to file
            tree = ET.ElementTree(tmx)
            ET.indent(tree, space="  ")  # Pretty print
            tree.write(f, encoding="utf-8", xml_declaration=True)

            return count

        # Atomic write
        result = self._atomic_write_with_result(path, write_tmx)

        logger.info(f"Exported TMX to {path} ({result} translation units)")
        return result

    def _sanitize_xml_text(self, text: Optional[str]) -> str:
        """Sanitize text for XML content.

        Removes invalid XML characters and ensures safe encoding.

        Args:
            text: Input text

        Returns:
            Sanitized text safe for XML
        """
        if not text:
            return ""

        # Remove null bytes and other invalid XML characters
        # Valid XML chars: #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD]
        sanitized = []
        for char in str(text):
            code = ord(char)
            if (code == 0x09 or code == 0x0A or code == 0x0D or
                (0x20 <= code <= 0xD7FF) or
                (0xE000 <= code <= 0xFFFD)):
                sanitized.append(char)

        return "".join(sanitized)
