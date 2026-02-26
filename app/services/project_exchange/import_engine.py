"""Import engine for project bundles with ID remapping."""

import logging
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from app.services.db_service import DBService
from app.services.project_exchange import bundle_format
from app.services.project_exchange.constants import (
    TABLE_INSERT_ORDER,
    TABLE_SCHEMA,
    NULLABLE_FK_COLUMNS,
    BUNDLE_FORMAT_VERSION,
    PRONUNCIATION_METADATA_FILENAME,
)
from app.services.project_exchange.dto import (
    ImportOptions,
    ImportReport,
)
from app.infra.fts_manager import ensure_fts_tables
from app.services.pronunciation_import_export_service import PronunciationImportExportService

logger = logging.getLogger(__name__)


class ProjectImportEngine:
    """Handles import of .hdleproj bundles with ID remapping."""

    def __init__(self):
        self.db_service = DBService.get_instance()

    def import_project(
        self,
        bundle_path: Path,
        options: ImportOptions = ImportOptions(),
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> ImportReport:
        """Import a project from a .hdleproj bundle.

        Args:
            bundle_path: Path to .hdleproj file
            options: Import options
            progress_callback: Optional progress callback (stage, current, total)

        Returns:
            ImportReport with results

        Raises:
            Exception: On import failure (caller should catch and handle)
        """
        start_time = time.time()
        temp_dir = None
        warnings = []
        host_conn = None
        payload_conn = None

        try:
            # Extract and validate bundle
            logger.info(f"Starting import from {bundle_path}")
            if progress_callback:
                progress_callback("Validating bundle...", 0, 100)

            temp_dir = Path(tempfile.mkdtemp(prefix="hdle_import_"))
            manifest, payload_path = bundle_format.read_bundle(bundle_path, temp_dir)

            # Preflight checks
            if progress_callback:
                progress_callback("Checking compatibility...", 5, 100)

            self._preflight_checks(manifest)

            # Handle name conflict
            final_project_name = self._resolve_project_name(
                manifest.project_name, options, warnings
            )

            # Compute ID offsets
            if progress_callback:
                progress_callback("Computing ID offsets...", 10, 100)

            host_conn = sqlite3.connect(self.db_service.db_manager.db_path)
            # FK checks will be done at COMMIT time
            host_conn.execute("PRAGMA foreign_keys = ON")

            payload_conn = sqlite3.connect(str(payload_path))
            payload_conn.execute("PRAGMA foreign_keys = ON")

            offsets = self._compute_offsets(host_conn, payload_conn)

            # Transactional import
            if progress_callback:
                progress_callback("Importing data...", 15, 100)

            new_project_id, table_counts = self._import_tables(
                host_conn,
                payload_conn,
                offsets,
                final_project_name,
                warnings,
                progress_callback,
            )

            pron_path = temp_dir / PRONUNCIATION_METADATA_FILENAME
            if pron_path.exists():
                self._import_pronunciation_metadata(pron_path, warnings)

            elapsed = time.time() - start_time
            logger.info(f"Import completed in {elapsed:.1f}s, new project ID: {new_project_id}")

            if progress_callback:
                progress_callback("Completed", 100, 100)

            return ImportReport(
                success=True,
                new_project_id=new_project_id,
                new_project_name=final_project_name,
                table_counts=table_counts,
                warnings=warnings,
                elapsed_seconds=elapsed,
            )

        except Exception as e:
            elapsed = time.time() - start_time
            logger.exception(f"Import failed after {elapsed:.1f}s")
            return ImportReport(
                success=False,
                elapsed_seconds=elapsed,
                error_message=str(e),
                warnings=warnings,
            )

        finally:
            if payload_conn is not None:
                try:
                    payload_conn.close()
                except Exception:
                    pass
            if host_conn is not None:
                try:
                    host_conn.close()
                except Exception:
                    pass
            # Cleanup temp directory
            if temp_dir and temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                    logger.debug(f"Cleaned up temp dir: {temp_dir}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup temp dir {temp_dir}: {e}")

    def _import_pronunciation_metadata(self, pron_path: Path, warnings: list[str]) -> None:
        """Import optional pronunciation metadata sidecar."""
        service = PronunciationImportExportService()
        try:
            with self.db_service.get_session() as session:
                result = service.import_file(
                    session,
                    in_path=pron_path,
                    delimiter="\t",
                    allow_auto_overwrite=False,
                )
                session.commit()
            warnings.append(
                "Pronunciation metadata imported: "
                f"processed={result.get('processed', 0)}, "
                f"updated={result.get('updated', 0)}, "
                f"skipped={result.get('skipped', 0)}, "
                f"failed={result.get('failed', 0)}"
            )
        except Exception as exc:
            warnings.append(f"Pronunciation metadata import skipped: {exc}")

    def _preflight_checks(self, manifest) -> None:
        """Run preflight validation checks.

        Args:
            manifest: ManifestInfo from bundle

        Raises:
            ValueError: If validation fails
        """
        # Check bundle format version
        if manifest.bundle_format_version != BUNDLE_FORMAT_VERSION:
            raise ValueError(
                f"Unsupported bundle format version {manifest.bundle_format_version}. "
                f"Expected {BUNDLE_FORMAT_VERSION}. Please update HDLE Premium."
            )

        # Check schema compatibility (payload schema must be <= host schema)
        from sqlalchemy import text
        with self.db_service.get_session() as session:
            result = session.execute(
                text("SELECT value FROM schema_meta WHERE key = 'schema_version'")
            ).fetchone()
            host_schema_version = int(result[0]) if result else 0

        if manifest.schema_version > host_schema_version:
            raise ValueError(
                f"Bundle requires schema v{manifest.schema_version}, but host DB is "
                f"v{host_schema_version}. Please update HDLE Premium."
            )

        logger.info("Preflight checks passed")

    def _resolve_project_name(
        self, original_name: str, options: ImportOptions, warnings: list[str]
    ) -> str:
        """Resolve project name, handling conflicts.

        Args:
            original_name: Original project name from bundle
            options: Import options
            warnings: List to append warnings to

        Returns:
            Final project name
        """
        if options.custom_name:
            return options.custom_name

        # Check for name conflict
        from sqlalchemy import text
        with self.db_service.get_session() as session:
            result = session.execute(
                text("SELECT COUNT(*) FROM dict_project WHERE name = :name"),
                {"name": original_name},
            ).fetchone()
            name_exists = result and result[0] > 0

        if name_exists:
            if options.rename_if_conflict:
                timestamp = datetime.now().strftime("%Y-%m-%d")
                new_name = f"{original_name} (imported {timestamp})"
                warnings.append(f"Project name '{original_name}' already exists, renamed to '{new_name}'")
                return new_name
            else:
                raise ValueError(f"Project name '{original_name}' already exists")

        return original_name

    def _compute_offsets(
        self, host_conn: sqlite3.Connection, payload_conn: sqlite3.Connection
    ) -> dict[str, int]:
        """Compute ID offsets for each table.

        Args:
            host_conn: Host DB connection
            payload_conn: Payload DB connection

        Returns:
            Dict of {table_name: offset}
        """
        offsets = {}

        for table_name in TABLE_INSERT_ORDER:
            schema = TABLE_SCHEMA.get(table_name)
            if not schema or schema["pk"] is None:
                # Composite PK table, no offset needed
                offsets[table_name] = 0
                continue

            pk_col = schema["pk"]

            # Get max ID in host
            try:
                result = host_conn.execute(
                    f"SELECT COALESCE(MAX({pk_col}), 0) FROM {table_name}"
                ).fetchone()
                host_max = result[0]
            except sqlite3.OperationalError:
                # Table might not exist in host (forward compatibility)
                host_max = 0

            # Get min/max ID in payload
            try:
                result = payload_conn.execute(
                    f"SELECT COALESCE(MIN({pk_col}), 1), COALESCE(MAX({pk_col}), 0) FROM {table_name}"
                ).fetchone()
                payload_min, payload_max = result
            except sqlite3.OperationalError:
                # Table might not exist in payload
                offsets[table_name] = 0
                continue

            # If payload is empty, offset is 0
            if payload_max == 0:
                offsets[table_name] = 0
                continue

            # Compute offset
            offset = host_max - payload_min + 1
            offsets[table_name] = offset
            logger.debug(
                f"{table_name}: host_max={host_max}, payload_min={payload_min}, offset={offset}"
            )

        return offsets

    def _import_tables(
        self,
        host_conn: sqlite3.Connection,
        payload_conn: sqlite3.Connection,
        offsets: dict[str, int],
        final_project_name: str,
        warnings: list[str],
        progress_callback: Optional[Callable[[str, int, int], None]],
    ) -> tuple[int, dict[str, int]]:
        """Import all tables in transaction.

        Args:
            host_conn: Host DB connection
            payload_conn: Payload DB connection
            offsets: ID offsets per table
            final_project_name: Final project name
            warnings: List to append warnings to
            progress_callback: Progress callback

        Returns:
            Tuple of (new_project_id, table_counts)

        Raises:
            Exception: On import failure (transaction will be rolled back)
        """
        host_conn.execute("BEGIN IMMEDIATE")

        # CRITICAL: Ensure FTS tables exist in host DB before importing
        # INSERT triggers on document_sentence/term_search reference sentence_fts/term_fts
        ensure_fts_tables(host_conn, schema="main", rebuild=False)
        logger.info("Ensured FTS tables exist in host DB")

        table_counts = {}
        new_project_id = None
        tm_global_id_map: dict[int, int] = {}

        try:
            total_tables = len(TABLE_INSERT_ORDER)

            for i, table_name in enumerate(TABLE_INSERT_ORDER):
                if progress_callback:
                    progress = 15 + (i * 80 // total_tables)
                    progress_callback(f"Importing {table_name}...", progress, 100)

                if table_name == "tm_global":
                    count, tm_global_id_map = self._import_tm_global_table(
                        host_conn,
                        payload_conn,
                    )
                    table_counts[table_name] = count
                    logger.debug(f"Imported {count} rows into {table_name}")
                    continue

                count = self._import_table(
                    host_conn,
                    payload_conn,
                    table_name,
                    offsets,
                    final_project_name if table_name == "dict_project" else None,
                    warnings,
                    tm_global_id_map,
                )
                table_counts[table_name] = count
                logger.debug(f"Imported {count} rows into {table_name}")

                # Capture new project ID
                if table_name == "dict_project" and count > 0:
                    result = host_conn.execute(
                        "SELECT project_id FROM dict_project WHERE name = ?",
                        (final_project_name,),
                    ).fetchone()
                    if result:
                        new_project_id = result[0]

            # Fix self-referencing FK on dict_project.general_corpus_id
            if new_project_id:
                self._fix_general_corpus_self_ref(
                    host_conn, payload_conn, offsets, new_project_id, warnings
                )

            host_conn.commit()
            logger.info("Transaction committed successfully")

            return new_project_id, table_counts

        except Exception as e:
            host_conn.rollback()
            logger.error(f"Transaction rolled back due to error: {e}")
            raise

    def _import_tm_global_table(
        self,
        host_conn: sqlite3.Connection,
        payload_conn: sqlite3.Connection,
    ) -> tuple[int, dict[int, int]]:
        """Merge payload tm_global rows into host by natural key and build ID map."""
        try:
            cursor = payload_conn.execute("SELECT * FROM tm_global")
            rows = cursor.fetchall()
            col_names = [desc[0] for desc in cursor.description]
        except sqlite3.OperationalError:
            return 0, {}

        if not rows:
            return 0, {}

        row_dicts = [dict(zip(col_names, row)) for row in rows]
        id_map: dict[int, int] = {}

        for row in row_dicts:
            payload_id = int(row["tm_global_id"])
            natural_key = (
                row["src_lang"],
                row["tgt_lang"],
                row["kind"],
                row["src_norm"],
            )
            existing = host_conn.execute(
                """
                SELECT tm_global_id
                FROM tm_global
                WHERE src_lang = ? AND tgt_lang = ? AND kind = ? AND src_norm = ?
                """,
                natural_key,
            ).fetchone()
            if existing:
                id_map[payload_id] = int(existing[0])
                continue

            host_conn.execute(
                """
                INSERT INTO tm_global (
                    src_lang, tgt_lang, kind, src_norm, src_text, translation,
                    status, origin, confidence, is_noise, noise_reason, notes,
                    source_tm_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("src_lang"),
                    row.get("tgt_lang"),
                    row.get("kind"),
                    row.get("src_norm"),
                    row.get("src_text"),
                    row.get("translation"),
                    row.get("status"),
                    row.get("origin"),
                    row.get("confidence"),
                    row.get("is_noise"),
                    row.get("noise_reason"),
                    row.get("notes"),
                    row.get("source_tm_id"),
                    row.get("created_at"),
                    row.get("updated_at"),
                ),
            )
            new_id = host_conn.execute("SELECT last_insert_rowid()").fetchone()
            id_map[payload_id] = int(new_id[0]) if new_id else payload_id

        return len(row_dicts), id_map

    def _import_table(
        self,
        host_conn: sqlite3.Connection,
        payload_conn: sqlite3.Connection,
        table_name: str,
        offsets: dict[str, int],
        override_name: Optional[str],
        warnings: list[str],
        tm_global_id_map: Optional[dict[int, int]] = None,
    ) -> int:
        """Import a single table with ID remapping.

        Args:
            host_conn: Host DB connection
            payload_conn: Payload DB connection
            table_name: Table to import
            offsets: ID offsets
            override_name: For dict_project, override the name
            warnings: List to append warnings to

        Returns:
            Number of rows imported
        """
        schema = TABLE_SCHEMA.get(table_name)
        if not schema:
            logger.warning(f"No schema for table {table_name}, skipping")
            return 0

        # Read all rows from payload
        try:
            cursor = payload_conn.execute(f"SELECT * FROM {table_name}")
            rows = cursor.fetchall()
            col_names = [desc[0] for desc in cursor.description]
        except sqlite3.OperationalError as e:
            logger.debug(f"Table {table_name} not in payload: {e}")
            return 0

        if not rows:
            return 0

        # Remap IDs and insert
        remapped_rows = []
        for row in rows:
            remapped_row = self._remap_row(
                table_name,
                col_names,
                row,
                offsets,
                override_name,
                tm_global_id_map=tm_global_id_map,
            )
            remapped_rows.append(remapped_row)

        # Chunked insert (200 rows per batch)
        placeholders = ",".join(["?"] * len(col_names))
        insert_sql = f"INSERT INTO {table_name} ({','.join(col_names)}) VALUES ({placeholders})"

        chunk_size = 200
        for i in range(0, len(remapped_rows), chunk_size):
            chunk = remapped_rows[i:i+chunk_size]
            try:
                host_conn.executemany(insert_sql, chunk)
            except sqlite3.IntegrityError as e:
                logger.error(f"FK constraint failed on table {table_name}, chunk {i}-{i+len(chunk)}")
                logger.error(f"First row in chunk: {chunk[0] if chunk else 'empty'}")
                logger.error(f"SQL: {insert_sql}")
                raise

        return len(remapped_rows)

    def _remap_row(
        self,
        table_name: str,
        col_names: list[str],
        row: tuple,
        offsets: dict[str, int],
        override_name: Optional[str],
        tm_global_id_map: Optional[dict[int, int]] = None,
    ) -> tuple:
        """Remap a single row's PK and FK values.

        Args:
            table_name: Table name
            col_names: Column names
            row: Row values
            offsets: ID offsets
            override_name: For dict_project.name, override value

        Returns:
            Remapped row tuple
        """
        schema = TABLE_SCHEMA[table_name]
        row_dict = dict(zip(col_names, row))

        # Remap PK
        pk_col = schema.get("pk")
        if pk_col and pk_col in row_dict and offsets[table_name] != 0:
            row_dict[pk_col] = row_dict[pk_col] + offsets[table_name]

        # Remap FKs
        fks = schema.get("fks", {})
        nullable_cols = NULLABLE_FK_COLUMNS.get(table_name, set())

        for fk_col, parent_table in fks.items():
            if fk_col not in row_dict:
                continue

            value = row_dict[fk_col]

            # Skip NULL values for nullable FKs
            if value is None and fk_col in nullable_cols:
                continue

            # Special case: dict_project.general_corpus_id self-ref
            # Set to NULL during insert, will be fixed in post-processing
            if table_name == "dict_project" and fk_col == "general_corpus_id":
                row_dict[fk_col] = None
                continue

            # tm_global has a natural key unique constraint; remap via precomputed payload->host map.
            if table_name == "tm_entry" and fk_col == "tm_global_id":
                if value is None:
                    continue
                mapped = None
                if tm_global_id_map is not None:
                    mapped = tm_global_id_map.get(int(value))
                row_dict[fk_col] = mapped
                continue

            # Remap
            if value is not None and offsets.get(parent_table, 0) != 0:
                row_dict[fk_col] = value + offsets[parent_table]

        # Override name for dict_project
        if table_name == "dict_project" and override_name:
            row_dict["name"] = override_name

        # Convert back to tuple in same order
        return tuple(row_dict[col] for col in col_names)

    def _fix_general_corpus_self_ref(
        self,
        host_conn: sqlite3.Connection,
        payload_conn: sqlite3.Connection,
        offsets: dict[str, int],
        new_project_id: int,
        warnings: list[str],
    ) -> None:
        """Fix self-referencing general_corpus_id after import.

        Args:
            host_conn: Host DB connection
            payload_conn: Payload DB connection
            offsets: ID offsets
            new_project_id: New project ID in host
            warnings: List to append warnings to
        """
        # Get original project_id and general_corpus_id from payload
        result = payload_conn.execute(
            "SELECT project_id, general_corpus_id FROM dict_project"
        ).fetchone()

        if not result:
            return

        payload_project_id, payload_general_corpus_id = result

        if payload_general_corpus_id is None:
            # No reference, nothing to fix
            return

        if payload_general_corpus_id == payload_project_id:
            # Self-reference: update to new_project_id
            host_conn.execute(
                "UPDATE dict_project SET general_corpus_id = ? WHERE project_id = ?",
                (new_project_id, new_project_id),
            )
            logger.info(f"Updated self-referencing general_corpus_id to {new_project_id}")
        else:
            # External reference: it was already set to NULL during import (not in bundle)
            warnings.append(
                "Project referenced external general corpus (not in bundle). "
                "Set to NULL. You may reassign it manually after import."
            )
