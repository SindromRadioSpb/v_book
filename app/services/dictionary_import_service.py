"""P3 Dictionary Import Service.

Provides dictionary import from CSV/XLSX with:
- Conflict policies (skip, overwrite, keep_both_as_variants)
- SHA256 deduplication
- Chunk commit for large files
- Progress tracking and cancellation
- Deterministic import reports
"""

import logging
import hashlib
import csv
import time
from pathlib import Path
from typing import Iterator, Callable, Optional, Literal, List
from sqlalchemy.orm import Session

from app.domain.dto import ImportRow, ImportReport, ImportInvalidRow, ImportConflict
from app.domain.normalization import normalize_for_tm
from app.infra.sa_models import DictSource, DictEntry
from app.infra.security import (
    validate_file_size,
    validate_path_security,
    sanitize_for_log,
    MAX_DICTIONARY_SIZE,
    ValidationError,
    PathSecurityError,
)

logger = logging.getLogger(__name__)

# Chunk size for commit batching
CHUNK_SIZE = 200


class DictionaryImportService:
    """Service for importing dictionaries from CSV/XLSX."""

    def compute_sha256(self, path: str) -> str:
        """Compute SHA256 hash of file.

        Args:
            path: File path

        Returns:
            SHA256 hex digest
        """
        sha256_hash = hashlib.sha256()
        with open(path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def parse_rows(
        self,
        path: str,
        fmt: Literal["csv", "xlsx"],
        default_kind: str = "lemma",
    ) -> Iterator[ImportRow]:
        """Parse rows from import file.

        Supports two formats:
        1. "2 column" (he, ru) - uses default_kind
        2. "Full" format with headers (case-insensitive):
           kind, src_lang, tgt_lang, src_text, translation, pos, domain,
           status, priority, notes, aliases

        Args:
            path: File path
            fmt: Format (csv or xlsx)
            default_kind: Default kind for 2-column format

        Yields:
            ImportRow instances
        """
        if fmt == "csv":
            yield from self._parse_csv(path, default_kind)
        elif fmt == "xlsx":
            yield from self._parse_xlsx(path, default_kind)
        else:
            raise ValueError(f"Unsupported format: {fmt}")

    def _parse_csv(self, path: str, default_kind: str) -> Iterator[ImportRow]:
        """Parse CSV file.

        Args:
            path: CSV file path
            default_kind: Default kind if 2-column format

        Yields:
            ImportRow instances
        """
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)

            if not rows:
                return

            # Detect format by headers
            header = [h.strip().lower() for h in rows[0]]

            # Check if full format (has 'kind' or 'src_text' columns)
            if "kind" in header or "src_text" in header:
                # Full format
                yield from self._parse_full_format(rows, header, "csv")
            else:
                # 2-column format (he, ru)
                yield from self._parse_2column_format(rows, default_kind)

    def _parse_xlsx(self, path: str, default_kind: str) -> Iterator[ImportRow]:
        """Parse XLSX file.

        Args:
            path: XLSX file path
            default_kind: Default kind if 2-column format

        Yields:
            ImportRow instances
        """
        try:
            import openpyxl
        except ImportError:
            raise ImportError("openpyxl is required for XLSX import. Install it with: pip install openpyxl")

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active

        rows = []
        for row in ws.iter_rows(values_only=True):
            # Convert None to empty string
            rows.append([str(cell) if cell is not None else "" for cell in row])

        wb.close()

        if not rows:
            return

        # Detect format
        header = [h.strip().lower() for h in rows[0]]

        if "kind" in header or "src_text" in header:
            yield from self._parse_full_format(rows, header, "xlsx")
        else:
            yield from self._parse_2column_format(rows, default_kind)

    def _parse_full_format(
        self,
        rows: List[List[str]],
        header: List[str],
        fmt: str,
    ) -> Iterator[ImportRow]:
        """Parse full format with headers.

        Expected columns (case-insensitive):
        kind, src_lang, tgt_lang, src_text, translation, pos, domain,
        status, priority, notes, aliases

        Args:
            rows: All rows including header
            header: Normalized header (lowercase)
            fmt: Format name for logging

        Yields:
            ImportRow instances
        """
        # Build column map
        col_map = {name: idx for idx, name in enumerate(header)}

        # Required columns
        required = ["src_text", "translation"]
        for req in required:
            if req not in col_map:
                logger.error(f"Missing required column '{req}' in {fmt} file")
                return

        # Parse data rows
        for row_idx, row in enumerate(rows[1:], start=2):  # Skip header, 1-indexed
            if not row or not any(row):  # Skip empty rows
                continue

            # Extract values
            src_text = row[col_map["src_text"]].strip() if "src_text" in col_map else ""
            translation = row[col_map["translation"]].strip() if "translation" in col_map else ""

            if not src_text or not translation:
                continue

            # Optional columns with defaults
            kind = row[col_map.get("kind", -1)].strip() if "kind" in col_map else "lemma"
            src_lang = row[col_map.get("src_lang", -1)].strip() if "src_lang" in col_map else "he"
            tgt_lang = row[col_map.get("tgt_lang", -1)].strip() if "tgt_lang" in col_map else "ru"
            pos = row[col_map.get("pos", -1)].strip() if "pos" in col_map and col_map["pos"] < len(row) else None
            domain = row[col_map.get("domain", -1)].strip() if "domain" in col_map and col_map["domain"] < len(row) else None
            status = row[col_map.get("status", -1)].strip() if "status" in col_map and col_map["status"] < len(row) else "approved"
            notes = row[col_map.get("notes", -1)].strip() if "notes" in col_map and col_map["notes"] < len(row) else None

            # Priority
            priority = None
            if "priority" in col_map and col_map["priority"] < len(row):
                try:
                    priority = int(row[col_map["priority"]])
                except (ValueError, IndexError):
                    pass

            # Aliases (semicolon-separated)
            aliases = None
            if "aliases" in col_map and col_map["aliases"] < len(row):
                aliases_str = row[col_map["aliases"]].strip()
                if aliases_str:
                    aliases = [a.strip() for a in aliases_str.split(";") if a.strip()]

            yield ImportRow(
                row_index=row_idx,
                kind=kind or "lemma",
                src_lang=src_lang or "he",
                tgt_lang=tgt_lang or "ru",
                src_text=src_text,
                translation=translation,
                pos=pos or None,
                domain=domain or None,
                status=status or "approved",
                priority=priority,
                notes=notes or None,
                aliases=aliases,
            )

    def _parse_2column_format(
        self,
        rows: List[List[str]],
        default_kind: str,
    ) -> Iterator[ImportRow]:
        """Parse 2-column format (he, ru).

        Args:
            rows: All rows (no header expected)
            default_kind: Kind to use for all entries

        Yields:
            ImportRow instances
        """
        for row_idx, row in enumerate(rows, start=1):
            if len(row) < 2:
                continue

            src_text = row[0].strip()
            translation = row[1].strip()

            if not src_text or not translation:
                continue

            yield ImportRow(
                row_index=row_idx,
                kind=default_kind,
                src_lang="he",
                tgt_lang="ru",
                src_text=src_text,
                translation=translation,
                pos=None,
                domain=None,
                status="approved",
                priority=None,
                notes=None,
                aliases=None,
            )

    def import_dictionary(
        self,
        session: Session,
        path: str,
        *,
        project_id: Optional[int],
        scope: Literal["global", "project"],
        on_conflict: Literal["skip", "overwrite", "keep_both_as_variants"],
        normalize_mode: Literal["strict", "compat"],
        default_kind: str = "lemma",
        default_status: str = "approved",
        progress_cb: Optional[Callable[[int, int], None]] = None,
        cancel_flag: Optional[Callable[[], bool]] = None,
        force_reimport: bool = False,
    ) -> ImportReport:
        """Import dictionary from file.

        Args:
            session: Database session
            path: File path (CSV or XLSX)
            project_id: Project ID (None for global scope)
            scope: Scope (global or project)
            on_conflict: Conflict policy
            normalize_mode: Normalization mode (for validation/cleaning, key is always strict)
            default_kind: Default kind for 2-column format
            default_status: Default status for new entries
            progress_cb: Progress callback (current, total)
            cancel_flag: Cancel check function
            force_reimport: Force reimport even if SHA256 exists

        Returns:
            ImportReport
        """
        start_time = time.time()

        # Validate scope
        if scope == "project" and project_id is None:
            raise ValueError("project_id required for project scope")
        if scope == "global" and project_id is not None:
            raise ValueError("project_id must be None for global scope")

        # Convert to Path for validation
        path_obj = Path(path)

        # Security: Validate path safety (block UNC, system dirs, resolve symlinks)
        try:
            safe_path = validate_path_security(path_obj, operation="dictionary import")
        except PathSecurityError as e:
            logger.warning(
                f"Path security check failed: {sanitize_for_log(str(path_obj))}, "
                f"reason={e.reason}"
            )
            raise ValueError(f"File path not allowed: {e.reason}")

        # Security: Validate file size to prevent DoS
        if not safe_path.exists():
            raise ValueError(f"File not found: {path}")

        try:
            validate_file_size(safe_path, MAX_DICTIONARY_SIZE, file_type="dictionary")
        except ValidationError as e:
            logger.warning(
                f"File size limit exceeded: {sanitize_for_log(path_obj.name)}, "
                f"size={e.value}"
            )
            raise ValueError(f"Dictionary file too large: {e.value} bytes")

        # Compute SHA256
        sha256 = self.compute_sha256(str(safe_path))

        # Check dedup
        if not force_reimport:
            existing = self._check_sha256_exists(session, sha256, project_id)
            if existing:
                logger.info(
                    f"File already imported: {sanitize_for_log(path_obj.name)} "
                    f"(sha256={sha256[:8]}...), skipping"
                )
                return ImportReport(
                    total=0,
                    added=0,
                    updated=0,
                    skipped=0,
                    conflicts=0,
                    invalid=0,
                    invalid_rows=[],
                    conflict_details=[],
                    dict_source_id=existing.dict_source_id,
                    sha256=sha256,
                    elapsed_ms=0.0,
                )

        # Detect format
        # Note: path_obj already created during path security validation
        if path_obj.suffix.lower() == ".csv":
            fmt = "csv"
        elif path_obj.suffix.lower() in [".xlsx", ".xls"]:
            fmt = "xlsx"
        else:
            raise ValueError(f"Unsupported file extension: {path_obj.suffix}")

        # Parse rows
        parsed_rows = list(self.parse_rows(path, fmt, default_kind))
        total_rows = len(parsed_rows)

        # Create DictSource
        dict_source = DictSource(
            project_id=project_id,
            name=path_obj.name,
            format=fmt,
            file_path=str(path_obj),
            sha256=sha256,
            row_count=total_rows,
            notes=f"Imported with conflict policy: {on_conflict}",
        )
        session.add(dict_source)
        session.flush()

        # Import with chunk commits
        counters = {
            "added": 0,
            "updated": 0,
            "skipped": 0,
            "conflicts": 0,
            "invalid": 0,
        }
        invalid_rows: List[ImportInvalidRow] = []
        conflict_details: List[ImportConflict] = []

        # Track processed entries within this batch (for conflict detection)
        # Key: (kind, src_lang, tgt_lang, src_norm, translation)
        processed_batch: set = set()

        for idx, row in enumerate(parsed_rows):
            # Check cancel
            if cancel_flag and cancel_flag():
                session.rollback()
                raise InterruptedError("Import cancelled by user")

            # Progress callback
            if progress_cb:
                progress_cb(idx + 1, total_rows)

            # Validate row
            if not row.src_text or not row.translation:
                invalid_rows.append(ImportInvalidRow(row.row_index, "Missing src_text or translation"))
                counters["invalid"] += 1
                continue

            # Normalize src_text (ALWAYS strict for dict_entry key)
            try:
                src_norm_result = normalize_for_tm(row.src_lang, row.src_text, row.kind, mode="strict")
                src_norm = src_norm_result.norm
            except Exception as e:
                invalid_rows.append(ImportInvalidRow(row.row_index, f"Normalization error: {e}"))
                counters["invalid"] += 1
                continue

            # Process main entry
            self._process_entry(
                session,
                dict_source.dict_source_id,
                row,
                src_norm,
                on_conflict,
                default_status,
                counters,
                conflict_details,
                processed_batch,
            )

            # Process aliases (each alias is a separate entry)
            if row.aliases:
                for alias in row.aliases:
                    if not alias:
                        continue

                    try:
                        alias_norm_result = normalize_for_tm(row.src_lang, alias, row.kind, mode="strict")
                        alias_norm = alias_norm_result.norm
                    except Exception as e:
                        logger.warning(f"Alias normalization failed: {alias}, error: {e}")
                        continue

                    # Create alias entry (same translation, different src_text)
                    alias_row = ImportRow(
                        row_index=row.row_index,
                        kind=row.kind,
                        src_lang=row.src_lang,
                        tgt_lang=row.tgt_lang,
                        src_text=alias,
                        translation=row.translation,
                        pos=row.pos,
                        domain=row.domain,
                        status=row.status,
                        priority=row.priority,
                        notes=row.notes,
                        aliases=None,
                    )

                    self._process_entry(
                        session,
                        dict_source.dict_source_id,
                        alias_row,
                        alias_norm,
                        on_conflict,
                        default_status,
                        counters,
                        conflict_details,
                        processed_batch,
                    )

            # Chunk commit
            if (idx + 1) % CHUNK_SIZE == 0:
                session.commit()
                logger.info(f"Committed chunk at row {idx + 1}/{total_rows}")

        # Final commit
        session.commit()

        elapsed_ms = (time.time() - start_time) * 1000

        logger.info(
            f"Import complete: {counters['added']} added, {counters['updated']} updated, "
            f"{counters['skipped']} skipped, {counters['invalid']} invalid in {elapsed_ms:.1f}ms"
        )

        return ImportReport(
            total=total_rows,
            added=counters["added"],
            updated=counters["updated"],
            skipped=counters["skipped"],
            conflicts=counters["conflicts"],
            invalid=counters["invalid"],
            invalid_rows=invalid_rows,
            conflict_details=conflict_details,
            dict_source_id=dict_source.dict_source_id,
            sha256=sha256,
            elapsed_ms=elapsed_ms,
        )

    def _check_sha256_exists(
        self,
        session: Session,
        sha256: str,
        project_id: Optional[int],
    ) -> Optional[DictSource]:
        """Check if SHA256 already imported in scope.

        Args:
            session: Database session
            sha256: SHA256 hash
            project_id: Project ID (None for global)

        Returns:
            Existing DictSource or None
        """
        return (
            session.query(DictSource)
            .filter(
                DictSource.sha256 == sha256,
                DictSource.project_id == project_id,
            )
            .first()
        )

    def _process_entry(
        self,
        session: Session,
        dict_source_id: int,
        row: ImportRow,
        src_norm: str,
        on_conflict: str,
        default_status: str,
        counters: dict,
        conflict_details: List[ImportConflict],
        processed_batch: set,
    ) -> None:
        """Process single entry with conflict policy.

        Args:
            session: Database session
            dict_source_id: Dict source ID
            row: Import row
            src_norm: Normalized source text (strict mode)
            on_conflict: Conflict policy
            default_status: Default status
            counters: Counters dict to update
            conflict_details: Conflict details list to append
            processed_batch: Set of already processed (kind, src_lang, tgt_lang, src_norm, translation) tuples
        """
        # Check for existing entry (UNIQUE constraint: dict_source_id, kind, src_lang, tgt_lang, src_norm, translation)
        # For dict_entry, the conflict key is: (dict_source_id, kind, src_lang, tgt_lang, src_norm, translation)
        # Wait, that includes translation in UNIQUE, so same src_norm with different translation is NOT a conflict per DB.
        # But per business logic, we want to detect when src_norm already exists (regardless of translation).

        # Track entry in batch for duplicate detection
        batch_key = (row.kind, row.src_lang, row.tgt_lang, src_norm, row.translation)

        # Check if exact duplicate in batch
        if batch_key in processed_batch:
            # Exact duplicate, skip
            counters["skipped"] += 1
            return

        # Check if same src_norm exists in batch (conflict)
        batch_conflict_key = (row.kind, row.src_lang, row.tgt_lang, src_norm)
        has_batch_conflict = any(
            (k, sl, tl, sn) == batch_conflict_key
            for (k, sl, tl, sn, trans) in processed_batch
        )

        # Query existing entries with same (dict_source_id, kind, src_lang, tgt_lang, src_norm)
        # This will find both committed and uncommitted (in session) entries
        # Force flush to make uncommitted entries visible to query
        if has_batch_conflict:
            session.flush()

        existing = (
            session.query(DictEntry)
            .filter(
                DictEntry.dict_source_id == dict_source_id,
                DictEntry.kind == row.kind,
                DictEntry.src_lang == row.src_lang,
                DictEntry.tgt_lang == row.tgt_lang,
                DictEntry.src_norm == src_norm,
            )
            .first()
        )

        if not existing:
            # No conflict, add new entry
            entry = DictEntry(
                dict_source_id=dict_source_id,
                kind=row.kind,
                src_lang=row.src_lang,
                tgt_lang=row.tgt_lang,
                src_text=row.src_text,
                src_norm=src_norm,
                translation=row.translation,
                pos=row.pos,
                domain=row.domain,
                status=row.status or default_status,
                priority=row.priority,
                notes=row.notes,
            )
            session.add(entry)
            counters["added"] += 1
            # Track in batch to prevent exact duplicates
            processed_batch.add(batch_key)
        else:
            # Conflict exists (same src_norm)
            counters["conflicts"] += 1

            if existing.translation == row.translation:
                # Exact duplicate (same src_norm AND translation), skip
                conflict_details.append(
                    ImportConflict(
                        row_index=row.row_index,
                        src_text=row.src_text,
                        src_norm=src_norm,
                        existing_translation=existing.translation,
                        incoming_translation=row.translation,
                        action_taken="skipped_duplicate",
                    )
                )
                counters["skipped"] += 1
                # Still track in batch to prevent duplicate processing
                processed_batch.add(batch_key)
                return

            # Different translation - apply conflict policy
            if on_conflict == "skip":
                conflict_details.append(
                    ImportConflict(
                        row_index=row.row_index,
                        src_text=row.src_text,
                        src_norm=src_norm,
                        existing_translation=existing.translation,
                        incoming_translation=row.translation,
                        action_taken="skipped",
                    )
                )
                counters["skipped"] += 1

            elif on_conflict == "overwrite":
                # Update existing entry
                old_translation = existing.translation
                existing.translation = row.translation
                existing.pos = row.pos or existing.pos
                existing.domain = row.domain or existing.domain
                existing.status = row.status or existing.status
                existing.priority = row.priority if row.priority is not None else existing.priority
                existing.notes = row.notes or existing.notes

                # Update batch tracking (remove old key, add new key)
                old_batch_key = (row.kind, row.src_lang, row.tgt_lang, src_norm, old_translation)
                processed_batch.discard(old_batch_key)
                processed_batch.add(batch_key)

                conflict_details.append(
                    ImportConflict(
                        row_index=row.row_index,
                        src_text=row.src_text,
                        src_norm=src_norm,
                        existing_translation=old_translation,
                        incoming_translation=row.translation,
                        action_taken="overwritten",
                    )
                )
                counters["updated"] += 1

            elif on_conflict == "keep_both_as_variants":
                # Keep both: add new entry with different translation
                # Since UNIQUE includes translation, this will work if translations differ
                entry = DictEntry(
                    dict_source_id=dict_source_id,
                    kind=row.kind,
                    src_lang=row.src_lang,
                    tgt_lang=row.tgt_lang,
                    src_text=row.src_text,
                    src_norm=src_norm,
                    translation=row.translation,
                    pos=row.pos,
                    domain=row.domain,
                    status=row.status or default_status,
                    priority=row.priority,
                    notes=row.notes,
                )
                session.add(entry)

                conflict_details.append(
                    ImportConflict(
                        row_index=row.row_index,
                        src_text=row.src_text,
                        src_norm=src_norm,
                        existing_translation=existing.translation,
                        incoming_translation=row.translation,
                        action_taken="kept_both",
                    )
                )
                counters["added"] += 1
                # Track in batch
                processed_batch.add(batch_key)
