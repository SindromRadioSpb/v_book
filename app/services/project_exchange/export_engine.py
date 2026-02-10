"""Export engine for project bundles."""

import logging
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable

from app import __version__ as APP_VERSION
from app.infra.security import validate_path_security
from app.services.db_service import DBService
from app.services.project_exchange import bundle_format
from app.services.project_exchange.constants import (
    TABLE_INSERT_ORDER,
    EXCLUDED_TABLES,
    BUNDLE_FORMAT_VERSION,
)
from app.services.project_exchange.dto import (
    ExportOptions,
    ExportReport,
    ManifestInfo,
)

logger = logging.getLogger(__name__)


class ProjectExportEngine:
    """Handles export of projects to .hdleproj bundles."""

    def __init__(self):
        self.db_service = DBService.get_instance()

    def export_project(
        self,
        project_id: int,
        out_path: Path,
        options: ExportOptions = ExportOptions(),
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> ExportReport:
        """Export a project to a .hdleproj bundle.

        Args:
            project_id: Project ID to export
            out_path: Output .hdleproj file path
            options: Export options
            progress_callback: Optional progress callback (stage, current, total)

        Returns:
            ExportReport with results

        Raises:
            Exception: On export failure (caller should catch and handle)
        """
        start_time = time.time()
        temp_dir = None

        try:
            # Preflight checks
            logger.info(f"Starting export of project {project_id} to {out_path}")
            self._preflight_checks(project_id, out_path)

            # Create temp directory
            temp_dir = Path(tempfile.mkdtemp(prefix="hdle_export_"))
            logger.info(f"Temp directory: {temp_dir}")

            # Create payload
            if progress_callback:
                progress_callback("Creating payload...", 0, 100)

            payload_path = temp_dir / "payload.sqlite"
            table_counts = self._create_payload(
                project_id, payload_path, options, progress_callback
            )

            # Get project metadata for manifest
            manifest = self._build_manifest(project_id, table_counts)

            # Create bundle
            if progress_callback:
                progress_callback("Creating bundle...", 95, 100)

            bundle_format.create_bundle(payload_path, manifest, out_path)

            elapsed = time.time() - start_time
            logger.info(f"Export completed in {elapsed:.1f}s: {out_path}")

            if progress_callback:
                progress_callback("Completed", 100, 100)

            return ExportReport(
                success=True,
                bundle_path=out_path,
                manifest=manifest,
                elapsed_seconds=elapsed,
            )

        except Exception as e:
            elapsed = time.time() - start_time
            logger.exception(f"Export failed after {elapsed:.1f}s")
            return ExportReport(
                success=False,
                elapsed_seconds=elapsed,
                error_message=str(e),
            )

        finally:
            # Cleanup temp directory
            if temp_dir and temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                    logger.debug(f"Cleaned up temp dir: {temp_dir}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup temp dir {temp_dir}: {e}")

    def _preflight_checks(self, project_id: int, out_path: Path) -> None:
        """Run preflight validation checks.

        Args:
            project_id: Project ID to export
            out_path: Output path

        Raises:
            ValueError: If validation fails
        """
        # Validate output path
        validate_path_security(out_path, operation="export_bundle")

        # Check project exists
        from sqlalchemy import text
        with self.db_service.get_session() as session:
            result = session.execute(
                text("SELECT COUNT(*) FROM dict_project WHERE project_id = :project_id"),
                {"project_id": project_id},
            ).fetchone()
            if not result or result[0] == 0:
                raise ValueError(f"Project {project_id} not found")

        # Check disk space (rough estimate: 2x current DB size)
        db_path = Path(self.db_service.db_manager.db_path)
        db_size = db_path.stat().st_size
        required_space = db_size * 2

        out_dir = out_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        stat = shutil.disk_usage(out_dir)
        if stat.free < required_space:
            raise ValueError(
                f"Insufficient disk space. Required: {required_space / 1024 / 1024:.1f} MB, "
                f"available: {stat.free / 1024 / 1024:.1f} MB"
            )

        logger.info("Preflight checks passed")

    def _create_payload(
        self,
        project_id: int,
        payload_path: Path,
        options: ExportOptions,
        progress_callback: Optional[Callable[[str, int, int], None]],
    ) -> dict[str, int]:
        """Create payload.sqlite with project data.

        Args:
            project_id: Project ID to export
            payload_path: Path to create payload
            options: Export options
            progress_callback: Progress callback

        Returns:
            Dict of {table_name: row_count}
        """
        host_db_path = self.db_service.db_manager.db_path

        # Create empty payload DB with schema
        payload_conn = sqlite3.connect(str(payload_path))
        payload_conn.execute("PRAGMA foreign_keys = ON")

        try:
            # Apply migrations to create schema
            migrations_dir = Path("app/infra/migrations")
            migration_files = sorted(migrations_dir.glob("*.sql"))

            logger.info(f"Applying {len(migration_files)} migrations to payload")
            for mig_file in migration_files:
                with open(mig_file, "r", encoding="utf-8") as f:
                    payload_conn.executescript(f.read())

            # Attach host DB
            payload_conn.execute(f"ATTACH DATABASE ? AS host", (str(host_db_path),))

            # Disable FK checks during export (we insert in topological order but ATTACH doesn't guarantee)
            payload_conn.execute("PRAGMA foreign_keys = OFF")

            # Copy data table by table
            table_counts = {}
            export_order = [t for t in TABLE_INSERT_ORDER if not options.include_snapshots and t != "project_snapshot" or options.include_snapshots]

            for i, table_name in enumerate(export_order):
                if progress_callback:
                    progress_callback(
                        f"Exporting {table_name}...",
                        i * 90 // len(export_order),
                        100,
                    )

                count = self._export_table(payload_conn, table_name, project_id)
                table_counts[table_name] = count
                logger.debug(f"Exported {count} rows from {table_name}")

            # Drop FTS5 virtual tables (will be rebuilt on import)
            logger.info("Dropping FTS5 virtual tables from payload")
            payload_conn.execute("DROP TABLE IF EXISTS sentence_fts")
            payload_conn.execute("DROP TABLE IF EXISTS term_fts")

            # Drop excluded tables
            logger.info("Dropping excluded tables from payload")
            for excluded_table in EXCLUDED_TABLES:
                payload_conn.execute(f"DROP TABLE IF EXISTS {excluded_table}")

            # Re-enable FK checks and commit
            payload_conn.execute("PRAGMA foreign_keys = ON")
            payload_conn.commit()

            logger.info(f"Payload created: {sum(table_counts.values())} total rows")
            return table_counts

        finally:
            payload_conn.close()

    def _export_table(self, payload_conn: sqlite3.Connection, table_name: str, project_id: int) -> int:
        """Export a single table from host to payload.

        Args:
            payload_conn: Payload DB connection (with host attached)
            table_name: Table to export
            project_id: Project ID filter

        Returns:
            Number of rows exported
        """
        logger.debug(f"Exporting table: {table_name}")
        # Table-specific export queries
        queries = {
            "library": f"""
                INSERT INTO library
                SELECT l.* FROM host.library l
                WHERE l.library_id = (SELECT library_id FROM host.dict_project WHERE project_id = ?)
            """,
            "dict_project": f"""
                INSERT INTO dict_project
                SELECT * FROM host.dict_project WHERE project_id = ?
            """,
            "source_corpus": f"""
                INSERT INTO source_corpus
                SELECT * FROM host.source_corpus WHERE project_id = ?
            """,
            "source_document": f"""
                INSERT INTO source_document
                SELECT d.* FROM host.source_document d
                JOIN host.source_corpus c ON d.corpus_id = c.corpus_id
                WHERE c.project_id = ?
            """,
            "document_text": f"""
                INSERT INTO document_text
                SELECT dt.* FROM host.document_text dt
                JOIN host.source_document d ON dt.doc_id = d.doc_id
                JOIN host.source_corpus c ON d.corpus_id = c.corpus_id
                WHERE c.project_id = ?
            """,
            "document_sentence": f"""
                INSERT INTO document_sentence
                SELECT ds.* FROM host.document_sentence ds
                JOIN host.source_document d ON ds.doc_id = d.doc_id
                JOIN host.source_corpus c ON d.corpus_id = c.corpus_id
                WHERE c.project_id = ?
            """,
            "lemma": f"""
                INSERT INTO lemma
                SELECT * FROM host.lemma WHERE project_id = ?
            """,
            "ngram": f"""
                INSERT INTO ngram
                SELECT * FROM host.ngram WHERE project_id = ?
            """,
            "ngram_component": f"""
                INSERT INTO ngram_component
                SELECT nc.* FROM host.ngram_component nc
                JOIN host.ngram n ON nc.ngram_id = n.ngram_id
                WHERE n.project_id = ?
            """,
            "lemma_doc_stat": f"""
                INSERT INTO lemma_doc_stat
                SELECT * FROM host.lemma_doc_stat WHERE project_id = ?
            """,
            "lemma_project_stat": f"""
                INSERT INTO lemma_project_stat
                SELECT * FROM host.lemma_project_stat WHERE project_id = ?
            """,
            "ngram_doc_stat": f"""
                INSERT INTO ngram_doc_stat
                SELECT * FROM host.ngram_doc_stat WHERE project_id = ?
            """,
            "ngram_project_stat": f"""
                INSERT INTO ngram_project_stat
                SELECT * FROM host.ngram_project_stat WHERE project_id = ?
            """,
            "term_cluster": f"""
                INSERT INTO term_cluster
                SELECT * FROM host.term_cluster WHERE project_id = ?
            """,
            "term_cluster_member": f"""
                INSERT INTO term_cluster_member
                SELECT tcm.* FROM host.term_cluster_member tcm
                JOIN host.term_cluster tc ON tcm.cluster_id = tc.cluster_id
                WHERE tc.project_id = ?
            """,
            "term_card": f"""
                INSERT INTO term_card
                SELECT * FROM host.term_card WHERE project_id = ?
            """,
            "translation_memory": f"""
                INSERT INTO translation_memory
                SELECT * FROM host.translation_memory WHERE project_id = ?
            """,
            "tm_entry": f"""
                INSERT INTO tm_entry
                SELECT * FROM host.tm_entry WHERE project_id = ?
            """,
            "tm_entry_history": f"""
                INSERT INTO tm_entry_history
                SELECT teh.* FROM host.tm_entry_history teh
                JOIN host.tm_entry te ON teh.tm_id = te.tm_id
                WHERE te.project_id = ?
            """,
            "tm_alias": f"""
                INSERT INTO tm_alias
                SELECT ta.* FROM host.tm_alias ta
                JOIN host.tm_entry te ON ta.tm_id = te.tm_id
                WHERE te.project_id = ?
            """,
            "dict_source": f"""
                INSERT INTO dict_source
                SELECT * FROM host.dict_source WHERE project_id = ?
            """,
            "dict_entry": f"""
                INSERT INTO dict_entry
                SELECT de.* FROM host.dict_entry de
                JOIN host.dict_source ds ON de.dict_source_id = ds.dict_source_id
                WHERE ds.project_id = ?
            """,
            "term_alias": f"""
                INSERT INTO term_alias
                SELECT * FROM host.term_alias WHERE project_id = ?
            """,
            "stopword_set": f"""
                INSERT INTO stopword_set
                SELECT * FROM host.stopword_set WHERE project_id = ?
            """,
            "stopword_item": f"""
                INSERT INTO stopword_item
                SELECT si.* FROM host.stopword_item si
                JOIN host.stopword_set ss ON si.stopset_id = ss.stopset_id
                WHERE ss.project_id = ?
            """,
            "term_search": f"""
                INSERT INTO term_search
                SELECT * FROM host.term_search WHERE project_id = ?
            """,
            "project_snapshot": f"""
                INSERT INTO project_snapshot
                SELECT * FROM host.project_snapshot WHERE project_id = ?
            """,
        }

        query = queries.get(table_name)
        if not query:
            logger.warning(f"No export query for table {table_name}, skipping")
            return 0

        try:
            cursor = payload_conn.execute(query, (project_id,))
            rowcount = cursor.rowcount
            logger.debug(f"  Exported {rowcount} rows from {table_name}")
            return rowcount
        except sqlite3.IntegrityError as e:
            logger.error(f"FK constraint failed while exporting table {table_name}")
            logger.error(f"Query: {query[:200]}...")
            raise

    def _build_manifest(self, project_id: int, table_counts: dict[str, int]) -> ManifestInfo:
        """Build manifest from project metadata and table counts.

        Args:
            project_id: Project ID
            table_counts: Dict of {table_name: row_count}

        Returns:
            ManifestInfo object
        """
        # Get project metadata
        from sqlalchemy import text
        with self.db_service.get_session() as session:
            result = session.execute(
                text("""
                SELECT name, src_lang, tgt_lang
                FROM dict_project
                WHERE project_id = :project_id
                """),
                {"project_id": project_id},
            ).fetchone()

            if not result:
                raise ValueError(f"Project {project_id} not found during manifest build")

            project_name, src_lang, tgt_lang = result

        # Get schema version
        with self.db_service.get_session() as session:
            result = session.execute(
                text("SELECT value FROM schema_meta WHERE key = 'schema_version'")
            ).fetchone()
            schema_version = int(result[0]) if result else 0

        return ManifestInfo(
            bundle_format_version=BUNDLE_FORMAT_VERSION,
            app_version=APP_VERSION,
            schema_version=schema_version,
            project_name=project_name,
            project_src_lang=src_lang,
            project_tgt_lang=tgt_lang,
            exported_at=datetime.now(timezone.utc).isoformat(),
            table_counts=table_counts,
        )
