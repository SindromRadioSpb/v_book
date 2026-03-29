"""Import engine for project bundles with ID remapping."""

import json
import logging
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from app.infra.fts_manager import ensure_fts_tables
from app.infra.write_gate import get_waiting_writer_count, run_serialized_db_write
from app.services.db_service import DBService
from app.services.project_exchange import bundle_format
from app.services.project_exchange.constants import (
    BUNDLE_FORMAT_VERSION,
    NULLABLE_FK_COLUMNS,
    PRONUNCIATION_METADATA_FILENAME,
    TABLE_INSERT_ORDER,
    TABLE_SCHEMA,
)
from app.services.project_exchange.dto import (
    ImportArtifactInfo,
    ImportOptions,
    ImportPreflightReport,
    ImportReport,
    ImportStageId,
    ImportStageRecord,
    ImportVerificationInfo,
)
from app.services.pronunciation_import_export_service import PronunciationImportExportService

logger = logging.getLogger(__name__)


class ImportCancelledError(Exception):
    """Raised when project import is cancelled by user request."""


class ProjectImportEngine:
    """Handles import of .hdleproj bundles with ID remapping."""

    _DEFAULT_LEMMA_BATCH_SIZE = 2000
    _MIN_LEMMA_BATCH_SIZE = 500
    _MAX_LEMMA_BATCH_SIZE = 10000
    _DEFAULT_LEMMA_GATE_BATCH_CAP = 1500
    _MIN_LEMMA_GATE_BATCH_CAP = 500
    _MAX_LEMMA_GATE_BATCH_CAP = 10000
    _DEFAULT_GENERIC_GATE_BATCH_SIZE = 200
    _MONOLITHIC_IMPORT_TABLES = {"library", "dict_project", "tm_global"}
    _STAGE_LABELS: dict[ImportStageId, str] = {
        ImportStageId.PREFLIGHT_BUNDLE: "Validating bundle artifact",
        ImportStageId.PREFLIGHT_COMPATIBILITY: "Checking compatibility",
        ImportStageId.PREPARE_CONNECTIONS: "Preparing import connections",
        ImportStageId.CHECK_IMPORTABILITY: "Checking importability",
        ImportStageId.COMPUTE_OFFSETS: "Computing ID offsets",
        ImportStageId.IMPORT_TABLES: "Importing data",
        ImportStageId.IMPORT_PRONUNCIATION_METADATA: "Importing pronunciation metadata",
        ImportStageId.VERIFY_IMPORTED_PROJECT: "Verifying imported project",
        ImportStageId.CLEANUP_PARTIAL_ROWS: "Cleaning partial import rows",
        ImportStageId.COMPLETED: "Completed",
    }

    def __init__(self):
        self.db_service = DBService.get_instance()
        self._lemma_batch_size = self._DEFAULT_LEMMA_BATCH_SIZE
        self._lemma_gate_batch_cap = self._DEFAULT_LEMMA_GATE_BATCH_CAP
        self._gate_trace_path: Path | None = None
        self._gate_trace_lock = threading.Lock()
        self._last_cleanup_status: str | None = None
        self._last_cleanup_error: str | None = None

    def import_project(
        self,
        bundle_path: Path,
        options: ImportOptions = ImportOptions(),
        progress_callback: Callable[[str, int, int], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        gate_trace_path: Path | None = None,
    ) -> ImportReport:
        """Import a project from a .hdleproj bundle.

        Args:
            bundle_path: Path to .hdleproj file
            options: Import options
            progress_callback: Optional progress callback (stage, current, total)
            gate_trace_path: Optional JSONL path for write-gate phase tracing.

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
        artifact_info: ImportArtifactInfo | None = None
        verification_info: ImportVerificationInfo | None = None
        cleanup_context: dict[str, object] = {
            "new_project_id": None,
            "inserted_library_ids": [],
            "inserted_tm_global_ids": [],
        }
        stage_history: list[ImportStageRecord] = []
        current_stage: ImportStageRecord | None = None
        result_report: ImportReport | None = None
        self._lemma_batch_size = self._resolve_lemma_batch_size()
        self._lemma_gate_batch_cap = self._resolve_lemma_gate_batch_cap()
        self._configure_gate_trace(gate_trace_path)
        self._last_cleanup_status = None
        self._last_cleanup_error = None

        def _begin_stage(stage_id: ImportStageId, *, detail: str | None = None) -> None:
            nonlocal current_stage
            now = time.time()
            if current_stage is not None and current_stage.ended_at is None:
                current_stage.ended_at = now
                current_stage.elapsed_seconds = max(0.0, now - current_stage.started_at)
                if current_stage.status == "running":
                    current_stage.status = "ok"
            current_stage = ImportStageRecord(
                stage_id=str(stage_id),
                stage_label=self._STAGE_LABELS[stage_id],
                status="running",
                started_at=now,
                detail=detail,
            )
            stage_history.append(current_stage)
            logger.info("Import stage start: %s", current_stage.stage_id)

        def _finish_stage(status: str = "ok", *, detail: str | None = None) -> None:
            nonlocal current_stage
            if current_stage is None or current_stage.ended_at is not None:
                return
            now = time.time()
            current_stage.ended_at = now
            current_stage.elapsed_seconds = max(0.0, now - current_stage.started_at)
            current_stage.status = status
            if detail:
                current_stage.detail = detail
            logger.info(
                "Import stage finish: %s status=%s detail=%s",
                current_stage.stage_id,
                status,
                current_stage.detail or "",
            )

        try:
            _begin_stage(ImportStageId.PREFLIGHT_BUNDLE)
            self._check_cancelled(cancel_check)

            # Extract and validate bundle
            logger.info(f"Starting import from {bundle_path}")
            if progress_callback:
                progress_callback(self._STAGE_LABELS[ImportStageId.PREFLIGHT_BUNDLE] + "...", 0, 100)

            temp_dir = Path(tempfile.mkdtemp(prefix="hdle_import_"))
            manifest, payload_path = bundle_format.read_bundle(bundle_path, temp_dir)
            artifact_info = self._build_import_artifact_info(bundle_path, manifest, payload_path)
            self._check_cancelled(cancel_check)
            _finish_stage(
                detail=(
                    f"project={manifest.project_name}; total_rows={artifact_info.total_rows:,}; "
                    f"payload_quick_check={artifact_info.payload_quick_check}"
                )
            )

            # Preflight checks
            _begin_stage(ImportStageId.PREFLIGHT_COMPATIBILITY)
            if progress_callback:
                progress_callback(
                    self._STAGE_LABELS[ImportStageId.PREFLIGHT_COMPATIBILITY] + "...",
                    5,
                    100,
                )

            self._preflight_checks(manifest)
            self._check_cancelled(cancel_check)

            # Handle name conflict
            final_project_name = self._resolve_project_name(
                manifest.project_name, options, warnings
            )
            _finish_stage(
                detail=(
                    f"host_schema={self._get_host_schema_version()}; "
                    f"target_name={final_project_name}"
                )
            )

            # Compute ID offsets
            _begin_stage(ImportStageId.PREPARE_CONNECTIONS)
            if progress_callback:
                progress_callback(
                    self._STAGE_LABELS[ImportStageId.PREPARE_CONNECTIONS] + "...",
                    10,
                    100,
                )

            host_conn = sqlite3.connect(self.db_service.db_manager.db_path)
            # FK checks will be done at COMMIT time
            host_conn.execute("PRAGMA foreign_keys = ON")

            payload_conn = sqlite3.connect(str(payload_path))
            payload_conn.execute("PRAGMA foreign_keys = ON")
            _finish_stage(detail="host_db_and_payload_opened")

            _begin_stage(ImportStageId.CHECK_IMPORTABILITY)
            if progress_callback:
                progress_callback(
                    self._STAGE_LABELS[ImportStageId.CHECK_IMPORTABILITY] + "...",
                    12,
                    100,
                )
            self._preflight_payload_document_uniqueness(payload_conn)
            self._check_cancelled(cancel_check)
            _finish_stage(detail="payload_duplicate_document_check=ok")

            _begin_stage(ImportStageId.COMPUTE_OFFSETS)
            if progress_callback:
                progress_callback(
                    self._STAGE_LABELS[ImportStageId.COMPUTE_OFFSETS] + "...",
                    15,
                    100,
                )

            offsets = self._compute_offsets(host_conn, payload_conn, cancel_check=cancel_check)
            _finish_stage(detail=f"tables_with_offsets={len(offsets)}")

            # Transactional import
            _begin_stage(ImportStageId.IMPORT_TABLES)
            if progress_callback:
                progress_callback(self._STAGE_LABELS[ImportStageId.IMPORT_TABLES] + "...", 18, 100)

            new_project_id, table_counts, cleanup_context = self._import_tables(
                host_conn,
                payload_conn,
                offsets,
                final_project_name,
                warnings,
                progress_callback,
                cancel_check=cancel_check,
            )
            self._check_cancelled(cancel_check)
            _finish_stage(
                detail=(
                    f"new_project_id={new_project_id}; imported_rows={sum(table_counts.values()):,}"
                )
            )

            pron_path = temp_dir / PRONUNCIATION_METADATA_FILENAME
            if pron_path.exists():
                _begin_stage(ImportStageId.IMPORT_PRONUNCIATION_METADATA)
                self._import_pronunciation_metadata(
                    pron_path,
                    warnings,
                    cancel_check=cancel_check,
                )
                self._check_cancelled(cancel_check)
                _finish_stage(detail="pronunciation_metadata_sidecar_processed")

            _begin_stage(ImportStageId.VERIFY_IMPORTED_PROJECT)
            if progress_callback:
                progress_callback(
                    self._STAGE_LABELS[ImportStageId.VERIFY_IMPORTED_PROJECT] + "...",
                    95,
                    100,
                )
            verification_info = self._verify_imported_project(
                host_conn,
                new_project_id,
                final_project_name,
                table_counts,
            )
            _finish_stage(
                detail=(
                    f"documents={verification_info.verified_document_count:,}; "
                    f"sentences={verification_info.verified_sentence_count:,}; "
                    f"lemmas={verification_info.verified_lemma_count:,}"
                )
            )

            elapsed = time.time() - start_time
            logger.info(f"Import completed in {elapsed:.1f}s, new project ID: {new_project_id}")

            _begin_stage(ImportStageId.COMPLETED)
            if progress_callback:
                progress_callback(self._STAGE_LABELS[ImportStageId.COMPLETED], 100, 100)
            _finish_stage(detail="import_successfully_verified")

            result_report = ImportReport(
                success=True,
                new_project_id=new_project_id,
                new_project_name=final_project_name,
                table_counts=table_counts,
                warnings=warnings,
                elapsed_seconds=elapsed,
                final_stage_id=str(ImportStageId.COMPLETED),
                final_stage_label=self._STAGE_LABELS[ImportStageId.COMPLETED],
                artifact_info=artifact_info,
                verification_info=verification_info,
            )

        except ImportCancelledError as exc:
            elapsed = time.time() - start_time
            logger.info(f"Import cancelled after {elapsed:.1f}s")
            failed_stage_id = current_stage.stage_id if current_stage is not None else None
            failed_stage_label = current_stage.stage_label if current_stage is not None else None
            _finish_stage(status="cancelled", detail=str(exc))
            result_report = ImportReport(
                success=False,
                elapsed_seconds=elapsed,
                error_message="Import cancelled by user",
                warnings=warnings,
                failure_code="import_cancelled",
                artifact_info=artifact_info,
                final_stage_id=failed_stage_id,
                final_stage_label=failed_stage_label,
            )
        except Exception as e:
            elapsed = time.time() - start_time
            logger.exception(f"Import failed after {elapsed:.1f}s")
            failed_stage_id = current_stage.stage_id if current_stage is not None else None
            failed_stage_label = current_stage.stage_label if current_stage is not None else None
            _finish_stage(status="failed", detail=str(e))
            if host_conn is not None:
                cleanup_project_id = cleanup_context.get("new_project_id")
                cleanup_library_ids = cleanup_context.get("inserted_library_ids", [])
                cleanup_tm_ids = cleanup_context.get("inserted_tm_global_ids", [])
                if cleanup_project_id is not None or cleanup_library_ids or cleanup_tm_ids:
                    try:
                        _begin_stage(ImportStageId.CLEANUP_PARTIAL_ROWS)
                        cleanup_status, cleanup_error = self._cleanup_partial_import(
                            host_conn,
                            new_project_id=cleanup_project_id,
                            inserted_library_ids=list(cleanup_library_ids),
                            inserted_tm_global_ids=list(cleanup_tm_ids),
                        )
                        _finish_stage(
                            status="ok" if cleanup_status != "failed" else "failed",
                            detail=cleanup_error or cleanup_status,
                        )
                    except Exception:
                        logger.exception("Unexpected cleanup-stage failure during import error handling")
            result_report = ImportReport(
                success=False,
                elapsed_seconds=elapsed,
                error_message=str(e),
                warnings=warnings,
                failure_code=self._classify_failure_code(e),
                artifact_info=artifact_info,
                final_stage_id=failed_stage_id,
                final_stage_label=failed_stage_label,
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
            self._gate_trace_path = None

            if result_report is None:
                result_report = ImportReport(
                    success=False,
                    elapsed_seconds=time.time() - start_time,
                    error_message="Import failed before report creation",
                    failure_code="import_internal_error",
                    warnings=warnings,
                    artifact_info=artifact_info,
                )

            if current_stage is not None and current_stage.ended_at is None:
                _finish_stage(
                    status="ok" if result_report.success else "failed",
                    detail=current_stage.detail,
                )

            if self._last_cleanup_status is not None:
                result_report.cleanup_status = self._last_cleanup_status
                result_report.cleanup_error_message = self._last_cleanup_error
            elif not result_report.success:
                result_report.cleanup_status = "not_needed"

            if not result_report.final_stage_id and stage_history:
                final_stage = stage_history[-1]
                result_report.final_stage_id = final_stage.stage_id
                result_report.final_stage_label = final_stage.stage_label
            result_report.stage_history = list(stage_history)

        return result_report

    def preflight_import(
        self,
        bundle_path: Path,
        options: ImportOptions = ImportOptions(),
    ) -> ImportPreflightReport:
        """Build a read-only import preview against the current host DB."""
        manifest = bundle_format.peek_manifest(bundle_path)
        self._preflight_checks(manifest)

        warnings: list[str] = []
        final_project_name = self._resolve_project_name(
            manifest.project_name,
            options,
            warnings,
        )

        host_schema_version = self._get_host_schema_version()
        name_conflict = self._project_name_exists(manifest.project_name)
        total_rows = int(sum((manifest.table_counts or {}).values()))

        return ImportPreflightReport(
            manifest=manifest,
            host_schema_version=host_schema_version,
            original_project_name=str(manifest.project_name),
            final_project_name=str(final_project_name),
            name_conflict=bool(name_conflict),
            total_rows=total_rows,
            warnings=list(warnings),
        )

    @classmethod
    def get_stage_label(cls, stage_id: str | ImportStageId | None) -> str:
        """Resolve a stable import stage label from its identifier."""
        if stage_id is None:
            return "Unknown stage"
        try:
            normalized = ImportStageId(str(stage_id))
        except ValueError:
            return str(stage_id)
        return cls._STAGE_LABELS.get(normalized, str(stage_id))

    def _build_import_artifact_info(
        self,
        bundle_path: Path,
        manifest,
        payload_path: Path,
    ) -> ImportArtifactInfo:
        payload_conn = sqlite3.connect(str(payload_path))
        try:
            quick_check_rows = [
                str(row[0]) for row in payload_conn.execute("PRAGMA quick_check(1)").fetchall()
            ]
        finally:
            payload_conn.close()

        if not quick_check_rows or any(row.lower() != "ok" for row in quick_check_rows):
            detail = "; ".join(quick_check_rows) if quick_check_rows else "empty result"
            raise ValueError(
                "Bundle payload quick_check failed before import mutation: " + detail
            )

        return ImportArtifactInfo(
            bundle_size_bytes=int(bundle_path.stat().st_size),
            payload_quick_check=quick_check_rows[0],
            manifest_project_name=str(manifest.project_name),
            total_rows=int(sum((manifest.table_counts or {}).values())),
        )

    @staticmethod
    def _classify_failure_code(error: Exception) -> str:
        error_str = str(error).lower()
        if "invalid zip file" in error_str:
            return "invalid_archive"
        if "checksum mismatch" in error_str or "corrupted" in error_str:
            return "corrupted_bundle"
        if "requires schema" in error_str or "unsupported bundle format" in error_str:
            return "incompatible_bundle"
        if "duplicate source documents" in error_str:
            return "payload_duplicate_documents"
        if "verification failed" in error_str:
            return "post_import_verification_failed"
        return "import_failed"

    @staticmethod
    def _check_cancelled(cancel_check: Callable[[], bool] | None) -> None:
        if cancel_check and bool(cancel_check()):
            raise ImportCancelledError("Import cancelled by user")

    def _resolve_lemma_batch_size(self) -> int:
        raw = os.environ.get("HDLE_IMPORT_LEMMA_BATCH_SIZE", "").strip()
        if not raw:
            return self._DEFAULT_LEMMA_BATCH_SIZE
        try:
            parsed = int(raw)
        except ValueError:
            logger.warning(
                "Invalid HDLE_IMPORT_LEMMA_BATCH_SIZE=%r; using default %s",
                raw,
                self._DEFAULT_LEMMA_BATCH_SIZE,
            )
            return self._DEFAULT_LEMMA_BATCH_SIZE
        clamped = max(self._MIN_LEMMA_BATCH_SIZE, min(self._MAX_LEMMA_BATCH_SIZE, parsed))
        if clamped != parsed:
            logger.info(
                "Clamped lemma batch size from %s to %s (allowed range: %s..%s)",
                parsed,
                clamped,
                self._MIN_LEMMA_BATCH_SIZE,
                self._MAX_LEMMA_BATCH_SIZE,
            )
        return clamped

    def _resolve_lemma_gate_batch_cap(self) -> int:
        raw = os.environ.get("HDLE_IMPORT_LEMMA_GATE_BATCH_CAP", "").strip()
        if not raw:
            return self._DEFAULT_LEMMA_GATE_BATCH_CAP
        try:
            parsed = int(raw)
        except ValueError:
            logger.warning(
                "Invalid HDLE_IMPORT_LEMMA_GATE_BATCH_CAP=%r; using default %s",
                raw,
                self._DEFAULT_LEMMA_GATE_BATCH_CAP,
            )
            return self._DEFAULT_LEMMA_GATE_BATCH_CAP
        clamped = max(
            self._MIN_LEMMA_GATE_BATCH_CAP,
            min(self._MAX_LEMMA_GATE_BATCH_CAP, parsed),
        )
        if clamped != parsed:
            logger.info(
                "Clamped lemma gate batch cap from %s to %s (allowed range: %s..%s)",
                parsed,
                clamped,
                self._MIN_LEMMA_GATE_BATCH_CAP,
                self._MAX_LEMMA_GATE_BATCH_CAP,
            )
        return clamped

    def _configure_gate_trace(self, gate_trace_path: Path | None) -> None:
        resolved: Path | None = None
        if gate_trace_path:
            resolved = Path(gate_trace_path)
        else:
            env_path = os.environ.get("HDLE_IMPORT_GATE_TRACE_JSONL", "").strip()
            if env_path:
                resolved = Path(env_path)

        if resolved is None:
            self._gate_trace_path = None
            return

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            self._gate_trace_path = resolved
        except Exception:
            logger.warning("Failed to configure gate trace path: %s", resolved, exc_info=True)
            self._gate_trace_path = None

    def _emit_gate_trace(
        self,
        *,
        event: str,
        phase: str,
        batch_idx: int | None = None,
        rows_in_batch: int | None = None,
        wait_ms: float | None = None,
        hold_ms: float | None = None,
        waiters: int | None = None,
    ) -> None:
        if self._gate_trace_path is None:
            return

        payload: dict[str, Any] = {
            "ts": time.time(),
            "event": event,
            "phase": phase,
        }
        if batch_idx is not None:
            payload["batch_idx"] = int(batch_idx)
        if rows_in_batch is not None:
            payload["rows_in_batch"] = int(rows_in_batch)
        if wait_ms is not None:
            payload["wait_ms"] = float(round(wait_ms, 3))
        if hold_ms is not None:
            payload["hold_ms"] = float(round(hold_ms, 3))
        if waiters is not None:
            payload["waiters"] = int(waiters)

        try:
            with self._gate_trace_lock:
                with self._gate_trace_path.open("a", encoding="utf-8") as trace_file:
                    trace_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            logger.debug("Failed to write import gate trace event", exc_info=True)

    def _cooperative_yield_if_needed(self, *, phase: str) -> None:
        waiters = get_waiting_writer_count()
        if waiters <= 0:
            return
        self._emit_gate_trace(
            event="gate_cooperative_yield",
            phase=phase,
            waiters=waiters,
        )
        time.sleep(0)

    def _run_serialized_write_tx(
        self,
        host_conn: sqlite3.Connection,
        *,
        operation: str,
        action: Callable[[], None],
        batch_idx: int | None = None,
        rows_in_batch: int | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        """Execute a write transaction through the shared process-local write gate."""

        acquire_start = time.perf_counter()
        self._emit_gate_trace(
            event="gate_acquire_start",
            phase=operation,
            batch_idx=batch_idx,
            rows_in_batch=rows_in_batch,
        )

        def _run_tx() -> None:
            self._check_cancelled(cancel_check)
            acquired_at = time.perf_counter()
            wait_ms = (acquired_at - acquire_start) * 1000.0
            self._emit_gate_trace(
                event="gate_acquired",
                phase=operation,
                batch_idx=batch_idx,
                rows_in_batch=rows_in_batch,
                wait_ms=wait_ms,
            )
            hold_start = time.perf_counter()
            host_conn.execute("BEGIN IMMEDIATE")
            try:
                action()
                host_conn.commit()
            except Exception:
                host_conn.rollback()
                raise
            finally:
                hold_ms = (time.perf_counter() - hold_start) * 1000.0
                self._emit_gate_trace(
                    event="gate_release",
                    phase=operation,
                    batch_idx=batch_idx,
                    rows_in_batch=rows_in_batch,
                    hold_ms=hold_ms,
                )

        run_serialized_db_write(
            operation,
            _run_tx,
            warn_wait_ms=250.0,
            warn_hold_ms=2500.0,
        )

    def _import_pronunciation_metadata(
        self,
        pron_path: Path,
        warnings: list[str],
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        """Import optional pronunciation metadata sidecar."""
        self._check_cancelled(cancel_check)
        service = PronunciationImportExportService()
        try:

            def _import_metadata() -> dict:
                with self.db_service.get_session() as session:
                    self._check_cancelled(cancel_check)
                    result_local = service.import_file(
                        session,
                        in_path=pron_path,
                        delimiter="\t",
                        allow_auto_overwrite=False,
                    )
                    self._check_cancelled(cancel_check)
                    session.commit()
                    return result_local

            acquire_start = time.perf_counter()
            self._emit_gate_trace(
                event="gate_acquire_start",
                phase="import.pronunciation_metadata",
            )

            def _run_import_metadata_traced() -> dict:
                acquired_at = time.perf_counter()
                self._emit_gate_trace(
                    event="gate_acquired",
                    phase="import.pronunciation_metadata",
                    wait_ms=(acquired_at - acquire_start) * 1000.0,
                )
                hold_start = time.perf_counter()
                try:
                    return _import_metadata()
                finally:
                    self._emit_gate_trace(
                        event="gate_release",
                        phase="import.pronunciation_metadata",
                        hold_ms=(time.perf_counter() - hold_start) * 1000.0,
                    )

            result = run_serialized_db_write(
                "import.pronunciation_metadata",
                _run_import_metadata_traced,
                warn_wait_ms=250.0,
                warn_hold_ms=2500.0,
            )
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
        host_schema_version = self._get_host_schema_version()

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
        if self._project_name_exists(original_name):
            if options.rename_if_conflict:
                timestamp = datetime.now().strftime("%Y-%m-%d")
                new_name = f"{original_name} (imported {timestamp})"
                warnings.append(
                    f"Project name '{original_name}' already exists, renamed to '{new_name}'"
                )
                return new_name
            else:
                raise ValueError(f"Project name '{original_name}' already exists")

        return original_name

    def _get_host_schema_version(self) -> int:
        from sqlalchemy import text

        with self.db_service.get_session() as session:
            result = session.execute(
                text("SELECT value FROM schema_meta WHERE key = 'schema_version'")
            ).fetchone()
            return int(result[0]) if result else 0

    def _project_name_exists(self, project_name: str) -> bool:
        from sqlalchemy import text

        with self.db_service.get_session() as session:
            result = session.execute(
                text("SELECT COUNT(*) FROM dict_project WHERE name = :name"),
                {"name": project_name},
            ).fetchone()
            return bool(result and result[0] > 0)

    def _preflight_payload_document_uniqueness(self, payload_conn: sqlite3.Connection) -> None:
        """Reject bundles that contain duplicate documents for the same corpus/content key."""
        try:
            rows = payload_conn.execute(
                """
                SELECT
                    corpus_id,
                    sha256,
                    COUNT(*) AS dup_count,
                    GROUP_CONCAT(doc_id, ', ') AS doc_ids
                FROM source_document
                WHERE COALESCE(TRIM(sha256), '') <> ''
                GROUP BY corpus_id, sha256
                HAVING COUNT(*) > 1
                ORDER BY dup_count DESC, corpus_id ASC
                LIMIT 5
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return

        if not rows:
            return

        samples = []
        for corpus_id, sha256, dup_count, doc_ids in rows:
            samples.append(
                f"corpus_id={int(corpus_id)} sha256={str(sha256)[:12]}... "
                f"count={int(dup_count)} doc_ids=[{doc_ids}]"
            )
        raise ValueError(
            "Bundle contains duplicate source documents with the same (corpus_id, sha256) key. "
            "Import stopped before writing to the host DB. "
            f"Examples: {'; '.join(samples)}"
        )

    def _compute_offsets(
        self,
        host_conn: sqlite3.Connection,
        payload_conn: sqlite3.Connection,
        *,
        cancel_check: Callable[[], bool] | None = None,
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
            self._check_cancelled(cancel_check)
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
        progress_callback: Callable[[str, int, int], None] | None,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[int, dict[str, int], dict[str, object]]:
        """Import all tables with bounded write-lock windows.

        Args:
            host_conn: Host DB connection
            payload_conn: Payload DB connection
            offsets: ID offsets per table
            final_project_name: Final project name
            warnings: List to append warnings to
            progress_callback: Progress callback
            cancel_check: Optional cancellation callback

        Returns:
            Tuple of (new_project_id, table_counts, cleanup_context)

        Raises:
            Exception: On import failure/cancellation
        """
        table_counts = {}
        new_project_id = None
        tm_global_id_map: dict[int, int] = {}
        inserted_tm_global_ids: list[int] = []
        inserted_library_ids: list[int] = []

        try:
            self._check_cancelled(cancel_check)

            # Keep FTS initialization in a short dedicated write transaction.
            def _ensure_fts() -> None:
                ensure_fts_tables(host_conn, schema="main", rebuild=False)

            self._run_serialized_write_tx(
                host_conn,
                operation="import.ensure_fts",
                action=_ensure_fts,
                cancel_check=cancel_check,
            )
            logger.info("Ensured FTS tables exist in host DB")

            total_tables = len(TABLE_INSERT_ORDER)

            for i, table_name in enumerate(TABLE_INSERT_ORDER):
                self._check_cancelled(cancel_check)

                if progress_callback:
                    progress = 15 + (i * 80 // total_tables)
                    progress_callback(f"Importing {table_name}...", progress, 100)

                progress_start = 15 + (i * 80 // total_tables)
                progress_end = 15 + ((i + 1) * 80 // total_tables)

                if table_name not in self._MONOLITHIC_IMPORT_TABLES:
                    batch_size = self._resolve_import_batch_size(table_name)
                    count = self._import_table_in_gate_batches(
                        host_conn,
                        payload_conn,
                        table_name,
                        offsets,
                        None,
                        warnings,
                        tm_global_id_map,
                        cancel_check=cancel_check,
                        batch_size=batch_size,
                        progress_callback=progress_callback,
                        progress_start=progress_start,
                        progress_end=progress_end,
                    )
                    table_counts[table_name] = count
                    logger.debug(
                        "Imported %s rows into %s using batch_size=%s",
                        count,
                        table_name,
                        batch_size,
                    )
                    continue

                def _import_current_table() -> None:
                    nonlocal new_project_id, tm_global_id_map
                    if table_name == "tm_global":
                        count, tm_global_id_map, new_tm_global_ids = self._import_tm_global_table(
                            host_conn,
                            payload_conn,
                            cancel_check=cancel_check,
                        )
                        if new_tm_global_ids:
                            inserted_tm_global_ids.extend(new_tm_global_ids)
                        table_counts[table_name] = count
                        logger.debug(f"Imported {count} rows into {table_name}")
                        return

                    inserted_pk_values = inserted_library_ids if table_name == "library" else None
                    count = self._import_table(
                        host_conn,
                        payload_conn,
                        table_name,
                        offsets,
                        final_project_name if table_name == "dict_project" else None,
                        warnings,
                        tm_global_id_map,
                        cancel_check=cancel_check,
                        inserted_pk_values=inserted_pk_values,
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

                self._run_serialized_write_tx(
                    host_conn,
                    operation=f"import.table.{table_name}",
                    action=_import_current_table,
                    cancel_check=cancel_check,
                )

            # Fix self-referencing FK on dict_project.general_corpus_id
            if new_project_id:

                def _fix_self_ref() -> None:
                    self._fix_general_corpus_self_ref(
                        host_conn, payload_conn, offsets, new_project_id, warnings
                    )

                self._run_serialized_write_tx(
                    host_conn,
                    operation="import.fix_general_corpus_self_ref",
                    action=_fix_self_ref,
                    cancel_check=cancel_check,
                )

            logger.info("Import committed successfully")

            return new_project_id, table_counts, {
                "new_project_id": new_project_id,
                "inserted_library_ids": list(inserted_library_ids),
                "inserted_tm_global_ids": list(inserted_tm_global_ids),
            }

        except ImportCancelledError:
            self._cleanup_partial_import(
                host_conn,
                new_project_id=new_project_id,
                inserted_library_ids=inserted_library_ids,
                inserted_tm_global_ids=inserted_tm_global_ids,
            )
            raise
        except Exception as e:
            logger.error(f"Import failed; running cleanup of partial inserts: {e}")
            self._cleanup_partial_import(
                host_conn,
                new_project_id=new_project_id,
                inserted_library_ids=inserted_library_ids,
                inserted_tm_global_ids=inserted_tm_global_ids,
            )
            raise

    def _cleanup_partial_import(
        self,
        host_conn: sqlite3.Connection,
        *,
        new_project_id: int | None,
        inserted_library_ids: list[int],
        inserted_tm_global_ids: list[int],
    ) -> tuple[str, str | None]:
        """Best-effort cleanup for partially imported rows after cancel/failure."""
        if new_project_id is None and not inserted_library_ids and not inserted_tm_global_ids:
            self._last_cleanup_status = "not_needed"
            self._last_cleanup_error = None
            return "not_needed", None

        try:

            def _cleanup_action() -> None:
                if new_project_id is not None:
                    host_conn.execute(
                        "DELETE FROM dict_project WHERE project_id = ?",
                        (int(new_project_id),),
                    )

                # Remove newly inserted global TM rows that are now unreferenced.
                for tm_global_id in sorted(set(inserted_tm_global_ids)):
                    host_conn.execute(
                        """
                        DELETE FROM tm_global
                        WHERE tm_global_id = ?
                          AND NOT EXISTS (
                            SELECT 1 FROM tm_entry WHERE tm_entry.tm_global_id = tm_global.tm_global_id
                          )
                        """,
                        (int(tm_global_id),),
                    )

                # Remove orphan libraries introduced by this import.
                for library_id in sorted(set(inserted_library_ids)):
                    host_conn.execute(
                        """
                        DELETE FROM library
                        WHERE library_id = ?
                          AND NOT EXISTS (
                            SELECT 1 FROM dict_project WHERE dict_project.library_id = library.library_id
                          )
                        """,
                        (int(library_id),),
                    )

            self._run_serialized_write_tx(
                host_conn,
                operation="import.cleanup_partial_rows",
                action=_cleanup_action,
            )
            logger.info("Cleaned up partial import rows")
            self._last_cleanup_status = "completed"
            self._last_cleanup_error = None
            return "completed", None
        except Exception as cleanup_exc:
            logger.warning("Failed to cleanup partial import rows: %s", cleanup_exc)
            self._last_cleanup_status = "failed"
            self._last_cleanup_error = str(cleanup_exc)
            return "failed", str(cleanup_exc)

    def _verify_imported_project(
        self,
        host_conn: sqlite3.Connection,
        new_project_id: int | None,
        final_project_name: str,
        table_counts: dict[str, int],
    ) -> ImportVerificationInfo:
        """Verify that the imported project is readable and internally coherent."""
        if new_project_id is None:
            raise ValueError("Post-import verification failed: imported project id is missing")

        project_row = host_conn.execute(
            "SELECT name FROM dict_project WHERE project_id = ?",
            (int(new_project_id),),
        ).fetchone()
        if project_row is None:
            raise ValueError("Post-import verification failed: imported project row is missing")

        project_name_matches = str(project_row[0]) == str(final_project_name)
        if not project_name_matches:
            raise ValueError(
                "Post-import verification failed: imported project name does not match the target name"
            )

        verified_corpus_count = int(
            host_conn.execute(
                "SELECT COUNT(*) FROM source_corpus WHERE project_id = ?",
                (int(new_project_id),),
            ).fetchone()[0]
            or 0
        )
        verified_document_count = int(
            host_conn.execute(
                """
                SELECT COUNT(*)
                FROM source_document sd
                JOIN source_corpus sc ON sc.corpus_id = sd.corpus_id
                WHERE sc.project_id = ?
                """,
                (int(new_project_id),),
            ).fetchone()[0]
            or 0
        )
        verified_sentence_count = int(
            host_conn.execute(
                """
                SELECT COUNT(*)
                FROM document_sentence ds
                JOIN source_document sd ON sd.doc_id = ds.doc_id
                JOIN source_corpus sc ON sc.corpus_id = sd.corpus_id
                WHERE sc.project_id = ?
                """,
                (int(new_project_id),),
            ).fetchone()[0]
            or 0
        )
        verified_lemma_count = int(
            host_conn.execute(
                "SELECT COUNT(*) FROM lemma WHERE project_id = ?",
                (int(new_project_id),),
            ).fetchone()[0]
            or 0
        )

        expected_corpus_count = int(table_counts.get("source_corpus", 0) or 0)
        expected_document_count = int(table_counts.get("source_document", 0) or 0)
        expected_sentence_count = int(table_counts.get("document_sentence", 0) or 0)
        expected_lemma_count = int(table_counts.get("lemma", 0) or 0)

        if verified_corpus_count != expected_corpus_count:
            raise ValueError(
                "Post-import verification failed: source_corpus count mismatch "
                f"(expected {expected_corpus_count}, got {verified_corpus_count})"
            )
        if verified_document_count != expected_document_count:
            raise ValueError(
                "Post-import verification failed: source_document count mismatch "
                f"(expected {expected_document_count}, got {verified_document_count})"
            )
        if verified_sentence_count != expected_sentence_count:
            raise ValueError(
                "Post-import verification failed: document_sentence count mismatch "
                f"(expected {expected_sentence_count}, got {verified_sentence_count})"
            )
        if verified_lemma_count != expected_lemma_count:
            raise ValueError(
                "Post-import verification failed: lemma count mismatch "
                f"(expected {expected_lemma_count}, got {verified_lemma_count})"
            )

        return ImportVerificationInfo(
            project_row_found=True,
            project_name_matches=True,
            verified_corpus_count=verified_corpus_count,
            verified_document_count=verified_document_count,
            verified_sentence_count=verified_sentence_count,
            verified_lemma_count=verified_lemma_count,
        )

    def _resolve_import_batch_size(self, table_name: str) -> int:
        if table_name == "lemma":
            return min(self._lemma_batch_size, self._lemma_gate_batch_cap)
        return self._DEFAULT_GENERIC_GATE_BATCH_SIZE

    def _import_tm_global_table(
        self,
        host_conn: sqlite3.Connection,
        payload_conn: sqlite3.Connection,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[int, dict[int, int], list[int]]:
        """Merge payload tm_global rows into host by natural key and build ID map."""
        try:
            cursor = payload_conn.execute("SELECT * FROM tm_global")
            rows = cursor.fetchall()
            col_names = [desc[0] for desc in cursor.description]
        except sqlite3.OperationalError:
            return 0, {}, []

        if not rows:
            return 0, {}, []

        row_dicts = [dict(zip(col_names, row)) for row in rows]
        id_map: dict[int, int] = {}
        inserted_ids: list[int] = []

        for idx, row in enumerate(row_dicts):
            if idx % 64 == 0:
                self._check_cancelled(cancel_check)
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
            mapped_id = int(new_id[0]) if new_id else payload_id
            id_map[payload_id] = mapped_id
            inserted_ids.append(mapped_id)

        return len(row_dicts), id_map, inserted_ids

    def _import_table_in_gate_batches(
        self,
        host_conn: sqlite3.Connection,
        payload_conn: sqlite3.Connection,
        table_name: str,
        offsets: dict[str, int],
        override_name: str | None,
        warnings: list[str],
        tm_global_id_map: dict[int, int] | None = None,
        *,
        cancel_check: Callable[[], bool] | None = None,
        batch_size: int,
        progress_callback: Callable[[str, int, int], None] | None = None,
        progress_start: int | None = None,
        progress_end: int | None = None,
    ) -> int:
        """Import a table in multiple short write-gate transactions."""
        self._check_cancelled(cancel_check)
        schema = TABLE_SCHEMA.get(table_name)
        if not schema:
            logger.warning(f"No schema for table {table_name}, skipping")
            return 0

        total_rows_expected = 0
        if progress_callback is not None:
            try:
                total_rows_expected = int(
                    payload_conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0] or 0
                )
            except sqlite3.OperationalError:
                total_rows_expected = 0

        try:
            cursor = payload_conn.execute(f"SELECT * FROM {table_name}")
            col_names = [desc[0] for desc in cursor.description]
        except sqlite3.OperationalError as e:
            logger.debug(f"Table {table_name} not in payload: {e}")
            return 0

        placeholders = ",".join(["?"] * len(col_names))
        insert_sql = f"INSERT INTO {table_name} ({','.join(col_names)}) VALUES ({placeholders})"

        total_rows = 0
        batch_idx = 0
        table_batch_size = batch_size
        if table_name == "lemma":
            table_batch_size = min(batch_size, self._lemma_gate_batch_cap)
            multiplier = max(1, (batch_size + table_batch_size - 1) // table_batch_size)
            read_chunk_size = table_batch_size * multiplier
        else:
            read_chunk_size = max(batch_size, 2048)

        last_progress_value: int | None = None

        while True:
            self._check_cancelled(cancel_check)
            raw_rows = cursor.fetchmany(read_chunk_size)
            if not raw_rows:
                break

            remapped_rows = []
            for idx, row in enumerate(raw_rows):
                if idx % 256 == 0:
                    self._check_cancelled(cancel_check)
                remapped_rows.append(
                    self._remap_row(
                        table_name,
                        col_names,
                        row,
                        offsets,
                        override_name,
                        tm_global_id_map=tm_global_id_map,
                    )
                )

            for offset in range(0, len(remapped_rows), table_batch_size):
                self._check_cancelled(cancel_check)
                batch_rows = remapped_rows[offset : offset + table_batch_size]
                rows_in_batch = len(batch_rows)

                def _insert_batch() -> None:
                    try:
                        host_conn.executemany(insert_sql, batch_rows)
                    except sqlite3.IntegrityError:
                        logger.error(
                            "FK constraint failed on table %s, batch_idx=%s, rows=%s",
                            table_name,
                            batch_idx,
                            rows_in_batch,
                        )
                        if batch_rows:
                            logger.error("First row in failed batch: %s", batch_rows[0])
                        logger.error("SQL: %s", insert_sql)
                        raise

                self._run_serialized_write_tx(
                    host_conn,
                    operation=f"import.table.{table_name}",
                    action=_insert_batch,
                    batch_idx=batch_idx,
                    rows_in_batch=rows_in_batch,
                    cancel_check=cancel_check,
                )
                total_rows += rows_in_batch
                batch_idx += 1

                if (
                    progress_callback is not None
                    and total_rows_expected > 0
                    and progress_start is not None
                    and progress_end is not None
                ):
                    span = max(0, progress_end - progress_start)
                    relative = min(1.0, total_rows / total_rows_expected)
                    progress_value = progress_start + int(round(relative * span))
                    if last_progress_value is None or progress_value > last_progress_value:
                        progress_callback(
                            f"Importing {table_name}... ({total_rows:,}/{total_rows_expected:,})",
                            min(progress_value, progress_end),
                            100,
                        )
                        last_progress_value = progress_value

                self._check_cancelled(cancel_check)
                self._cooperative_yield_if_needed(phase=f"import.table.{table_name}")

        return total_rows

    def _import_table(
        self,
        host_conn: sqlite3.Connection,
        payload_conn: sqlite3.Connection,
        table_name: str,
        offsets: dict[str, int],
        override_name: str | None,
        warnings: list[str],
        tm_global_id_map: dict[int, int] | None = None,
        *,
        cancel_check: Callable[[], bool] | None = None,
        inserted_pk_values: list[int] | None = None,
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
        self._check_cancelled(cancel_check)
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
        for idx, row in enumerate(rows):
            if idx % 256 == 0:
                self._check_cancelled(cancel_check)
            remapped_row = self._remap_row(
                table_name,
                col_names,
                row,
                offsets,
                override_name,
                tm_global_id_map=tm_global_id_map,
            )
            remapped_rows.append(remapped_row)

        if inserted_pk_values is not None:
            pk_col = schema.get("pk")
            if pk_col and pk_col in col_names:
                pk_idx = col_names.index(pk_col)
                for remapped_row in remapped_rows:
                    pk_value = remapped_row[pk_idx]
                    if pk_value is not None:
                        inserted_pk_values.append(int(pk_value))

        # Chunked insert (200 rows per batch)
        placeholders = ",".join(["?"] * len(col_names))
        insert_sql = f"INSERT INTO {table_name} ({','.join(col_names)}) VALUES ({placeholders})"

        chunk_size = 200
        for i in range(0, len(remapped_rows), chunk_size):
            self._check_cancelled(cancel_check)
            chunk = remapped_rows[i : i + chunk_size]
            try:
                host_conn.executemany(insert_sql, chunk)
            except sqlite3.IntegrityError:
                logger.error(
                    f"FK constraint failed on table {table_name}, chunk {i}-{i+len(chunk)}"
                )
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
        override_name: str | None,
        tm_global_id_map: dict[int, int] | None = None,
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
