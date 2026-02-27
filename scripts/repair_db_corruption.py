#!/usr/bin/env python3
"""SQLite corruption triage and salvage pipeline.

Primary target symptom:
    database disk image is malformed
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add project root to path for direct script execution.
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.infra.fts_manager import check_fts_exists  # noqa: E402
from scripts.repair_fts_schema import repair_fts_schema  # noqa: E402


logger = logging.getLogger(__name__)

KEY_TABLES = (
    "dict_project",
    "source_document",
    "document_sentence",
    "lemma",
    "tm_entry",
)
TM_ENTRY_INDEX_PROBE_COLUMNS = (
    "tm_id",
    "project_id",
    "kind",
    "src_norm",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _connect(db_path: Path, *, readonly: bool = True) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=30)
    else:
        conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def _run_pragma(conn: sqlite3.Connection, pragma_sql: str) -> dict[str, Any]:
    try:
        rows = [str(row[0]) for row in conn.execute(pragma_sql).fetchall()]
        ok = bool(rows) and all(value.lower() == "ok" for value in rows)
        return {
            "ok": ok,
            "rows": rows,
            "error": None,
            "sql": pragma_sql,
        }
    except sqlite3.Error as exc:
        return {
            "ok": False,
            "rows": [],
            "error": str(exc),
            "sql": pragma_sql,
        }


def _probe_sql(conn: sqlite3.Connection, sql: str) -> dict[str, Any]:
    try:
        conn.execute(sql).fetchone()
        return {
            "ok": True,
            "error": None,
            "sql": sql,
        }
    except sqlite3.Error as exc:
        return {
            "ok": False,
            "error": str(exc),
            "sql": sql,
        }


def _probe_tm_entry_indexes(conn: sqlite3.Connection) -> tuple[list[str], list[dict[str, Any]]]:
    failing_objects: list[str] = []
    failing_sql_examples: list[dict[str, Any]] = []

    try:
        index_rows = conn.execute("PRAGMA index_list(tm_entry)").fetchall()
    except sqlite3.Error as exc:
        failing_objects.append("tm_entry")
        failing_sql_examples.append(
            {
                "phase": "tm_entry_index_list",
                "sql": "PRAGMA index_list(tm_entry)",
                "error": str(exc),
            }
        )
        return failing_objects, failing_sql_examples

    for row in index_rows:
        index_name = str(row[1])
        for column in TM_ENTRY_INDEX_PROBE_COLUMNS:
            sql = (
                f'SELECT "{column}" FROM tm_entry INDEXED BY "{index_name}" '
                f'ORDER BY "{column}" LIMIT 1'
            )
            try:
                conn.execute(sql).fetchone()
                break
            except sqlite3.Error as exc:
                failing_objects.append(f"index:{index_name}")
                failing_sql_examples.append(
                    {
                        "phase": "tm_entry_index_probe",
                        "index": index_name,
                        "sql": sql,
                        "error": str(exc),
                    }
                )
                break

    return sorted(set(failing_objects)), failing_sql_examples


def _safe_table_count(db_path: Path, table_name: str) -> dict[str, Any]:
    try:
        conn = _connect(db_path, readonly=True)
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
            return {"count": int(row[0]) if row else 0, "error": None}
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {"count": None, "error": str(exc)}


def diagnose_db_corruption(db_path: Path, *, deep: bool = False) -> dict[str, Any]:
    started = time.perf_counter()
    diagnosis: dict[str, Any] = {
        "status": "OK",
        "db_path": str(db_path),
        "quick_check": {},
        "integrity_check": None,
        "tm_entry_probe": {},
        "failing_objects": [],
        "failing_sql_examples": [],
        "elapsed_s": None,
    }

    failing_objects: list[str] = []
    failing_sql_examples: list[dict[str, Any]] = []

    try:
        conn = _connect(db_path, readonly=True)
    except sqlite3.Error as exc:
        diagnosis["status"] = "CORRUPT"
        diagnosis["quick_check"] = {
            "ok": False,
            "rows": [],
            "error": str(exc),
            "sql": "PRAGMA quick_check(10)",
        }
        diagnosis["tm_entry_probe"] = {
            "ok": False,
            "error": str(exc),
            "sql": "SELECT 1 FROM tm_entry LIMIT 1",
        }
        diagnosis["failing_objects"] = ["database_open"]
        diagnosis["failing_sql_examples"] = [
            {
                "phase": "database_open",
                "sql": "sqlite3.connect(mode=ro)",
                "error": str(exc),
            }
        ]
        diagnosis["elapsed_s"] = round(time.perf_counter() - started, 3)
        return diagnosis

    try:
        quick_check = _run_pragma(conn, "PRAGMA quick_check(10)")
        diagnosis["quick_check"] = quick_check
        if not quick_check["ok"]:
            failing_objects.append("database")
            failing_sql_examples.append(
                {
                    "phase": "quick_check",
                    "sql": quick_check.get("sql"),
                    "error": quick_check.get("error") or "; ".join(quick_check.get("rows", [])),
                }
            )

        if deep:
            integrity_check = _run_pragma(conn, "PRAGMA integrity_check")
            diagnosis["integrity_check"] = integrity_check
            if not integrity_check["ok"]:
                failing_objects.append("database")
                failing_sql_examples.append(
                    {
                        "phase": "integrity_check",
                        "sql": integrity_check.get("sql"),
                        "error": integrity_check.get("error") or "; ".join(integrity_check.get("rows", [])),
                    }
                )

        tm_entry_probe = _probe_sql(conn, "SELECT 1 FROM tm_entry LIMIT 1")
        diagnosis["tm_entry_probe"] = tm_entry_probe
        if not tm_entry_probe["ok"]:
            failing_objects.append("tm_entry")
            failing_sql_examples.append(
                {
                    "phase": "tm_entry_probe",
                    "sql": tm_entry_probe["sql"],
                    "error": tm_entry_probe["error"],
                }
            )

        index_objects, index_sql_examples = _probe_tm_entry_indexes(conn)
        failing_objects.extend(index_objects)
        failing_sql_examples.extend(index_sql_examples)
    finally:
        conn.close()

    failing_objects = sorted(set(failing_objects))
    diagnosis["failing_objects"] = failing_objects
    diagnosis["failing_sql_examples"] = failing_sql_examples
    if failing_objects:
        diagnosis["status"] = "CORRUPT"

    diagnosis["elapsed_s"] = round(time.perf_counter() - started, 3)
    return diagnosis


def _locate_sqlite3_binary(explicit_path: str | None) -> Path | None:
    if explicit_path:
        path = Path(explicit_path).expanduser()
        if path.exists():
            return path
        return None

    for candidate in ("sqlite3.exe", "sqlite3"):
        resolved = shutil.which(candidate)
        if resolved:
            return Path(resolved)
    return None


def _create_backup(db_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.with_name(f"{db_path.stem}.bak_{timestamp}{db_path.suffix}")
    logger.info("Creating backup: %s", backup_path)
    shutil.copy2(db_path, backup_path)
    return backup_path


def _run_sqlite_recover_pipeline(
    *,
    sqlite3_bin: Path,
    source_db: Path,
    recovered_db: Path,
    log_path: Path,
) -> dict[str, Any]:
    cmd_recover = [str(sqlite3_bin), str(source_db), ".recover"]
    cmd_apply = [str(sqlite3_bin), str(recovered_db), "-cmd", ".bail off"]

    with log_path.open("wb") as log_file:
        log_file.write(f"[recover_cmd] {' '.join(cmd_recover)}\n".encode("utf-8", errors="replace"))
        log_file.write(f"[apply_cmd] {' '.join(cmd_apply)}\n".encode("utf-8", errors="replace"))
        log_file.flush()

        proc_recover = subprocess.Popen(
            cmd_recover,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc_recover.stdout is not None

        proc_apply = subprocess.Popen(
            cmd_apply,
            stdin=proc_recover.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc_recover.stdout is not None:
            proc_recover.stdout.close()

        apply_stdout, apply_stderr = proc_apply.communicate()
        recover_stderr = b""
        if proc_recover.stderr is not None:
            recover_stderr = proc_recover.stderr.read()
        recover_rc = int(proc_recover.wait())

        apply_rc = int(proc_apply.returncode or 0)

        log_file.write(f"[recover_rc] {recover_rc}\n".encode("utf-8", errors="replace"))
        log_file.write(f"[apply_rc] {apply_rc}\n".encode("utf-8", errors="replace"))
        if recover_stderr:
            log_file.write(b"[recover_stderr]\n")
            log_file.write(recover_stderr[:200_000])
            log_file.write(b"\n")
        if apply_stderr:
            log_file.write(b"[apply_stderr]\n")
            log_file.write(apply_stderr[:200_000])
            log_file.write(b"\n")
        if apply_stdout:
            log_file.write(b"[apply_stdout]\n")
            log_file.write(apply_stdout[:200_000])
            log_file.write(b"\n")

    recovered_exists = recovered_db.exists()
    recovered_size = recovered_db.stat().st_size if recovered_exists else 0
    ok = recover_rc == 0 and apply_rc == 0 and recovered_exists and recovered_size > 0
    return {
        "ok": ok,
        "recover_rc": recover_rc,
        "apply_rc": apply_rc,
        "recovered_exists": recovered_exists,
        "recovered_size": recovered_size,
        "log_path": str(log_path),
        "error": None if (recover_rc == 0 and recovered_exists and recovered_size > 0) else "sqlite3 .recover pipeline failed",
    }


def _validate_recovered_db(db_path: Path) -> dict[str, Any]:
    validation: dict[str, Any] = {
        "quick_check": {},
        "tm_entry_probe": {},
        "fts_status": {},
        "schema_version": None,
        "error": None,
    }

    try:
        conn = _connect(db_path, readonly=True)
    except sqlite3.Error as exc:
        validation["error"] = str(exc)
        validation["quick_check"] = {"ok": False, "rows": [], "error": str(exc)}
        validation["tm_entry_probe"] = {"ok": False, "error": str(exc)}
        validation["fts_status"] = {"ok": False, "error": str(exc)}
        return validation

    try:
        validation["quick_check"] = _run_pragma(conn, "PRAGMA quick_check(10)")
        validation["tm_entry_probe"] = _probe_sql(conn, "SELECT 1 FROM tm_entry LIMIT 1")

        try:
            sentence_fts_exists, term_fts_exists = check_fts_exists(conn)
            trigger_rows = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='trigger'
                  AND name IN ('trg_sentence_ai', 'trg_sentence_ad', 'trg_sentence_au',
                               'trg_term_search_ai', 'trg_term_search_ad', 'trg_term_search_au')
                """
            ).fetchall()
            validation["fts_status"] = {
                "ok": bool(sentence_fts_exists and term_fts_exists),
                "sentence_fts_exists": bool(sentence_fts_exists),
                "term_fts_exists": bool(term_fts_exists),
                "trigger_count": len(trigger_rows),
            }
        except sqlite3.Error as exc:
            validation["fts_status"] = {
                "ok": False,
                "error": str(exc),
            }

        try:
            row = conn.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            if row:
                validation["schema_version"] = int(row[0])
        except sqlite3.Error:
            validation["schema_version"] = None
    finally:
        conn.close()

    return validation


def _build_table_count_compare(original_db: Path, recovered_db: Path) -> dict[str, Any]:
    compare: dict[str, Any] = {}
    for table_name in KEY_TABLES:
        before = _safe_table_count(original_db, table_name)
        after = _safe_table_count(recovered_db, table_name)
        delta = None
        if before["count"] is not None and after["count"] is not None:
            delta = int(after["count"]) - int(before["count"])
        compare[table_name] = {
            "original_count": before["count"],
            "original_error": before["error"],
            "recovered_count": after["count"],
            "recovered_error": after["error"],
            "delta": delta,
        }
    return compare


def repair_db_corruption(
    *,
    db_path: Path,
    deep: bool = False,
    diagnose_only: bool = False,
    backup: bool = True,
    sqlite3_bin: str | None = None,
    recovered_db_path: Path | None = None,
    fts_rebuild: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    summary: dict[str, Any] = {
        "status": "FAILED",
        "started_at_utc": _utc_now(),
        "db_path": str(db_path),
        "diagnose_only": bool(diagnose_only),
        "backup_enabled": bool(backup),
        "deep_integrity_check": bool(deep),
        "backup_path": None,
        "recovered_db_path": None,
        "diagnosis": {},
        "actions": [],
        "recovered_warnings": [],
        "validation_results": {},
        "table_count_compare": {},
        "error": None,
    }

    try:
        diagnosis = diagnose_db_corruption(db_path, deep=deep)
        summary["diagnosis"] = diagnosis

        if diagnosis["status"] == "OK":
            summary["status"] = "OK"
            return summary

        summary["status"] = "CORRUPT"
        if diagnose_only:
            summary["error"] = "Corruption detected; run salvage mode to recover into a new DB."
            return summary

        if backup:
            backup_path = _create_backup(db_path)
            summary["backup_path"] = str(backup_path)
            summary["actions"].append(f"backup_created:{backup_path}")

        sqlite_bin_path = _locate_sqlite3_binary(sqlite3_bin)
        if not sqlite_bin_path:
            summary["status"] = "FAILED"
            summary["error"] = (
                "sqlite3 CLI not found. Install sqlite3 and rerun, or pass --sqlite3-bin <path>."
            )
            return summary

        logs_dir = project_root / "build" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        recover_log_path = logs_dir / f"db_recover_{ts}.log"

        if recovered_db_path is None:
            recovered_db_path = db_path.with_name(f"{db_path.stem}.recovered_{ts}{db_path.suffix}")
        summary["recovered_db_path"] = str(recovered_db_path)

        recover_result = _run_sqlite_recover_pipeline(
            sqlite3_bin=sqlite_bin_path,
            source_db=db_path,
            recovered_db=recovered_db_path,
            log_path=recover_log_path,
        )
        summary["actions"].append(f"recover_pipeline_log:{recover_log_path}")
        summary["actions"].append(
            "recover_pipeline_status:"
            f"recover_rc={recover_result['recover_rc']},apply_rc={recover_result['apply_rc']}"
        )
        if (
            recover_result["recover_rc"] != 0
            or not recover_result.get("recovered_exists")
            or int(recover_result.get("recovered_size", 0)) <= 0
        ):
            summary["status"] = "FAILED"
            summary["error"] = recover_result["error"]
            return summary
        if recover_result["apply_rc"] != 0:
            summary["recovered_warnings"].append(
                "recover_apply_nonzero_exit: "
                f"apply_rc={recover_result['apply_rc']} (see {recover_result['log_path']})"
            )

        fts_summary = repair_fts_schema(
            db_path=recovered_db_path,
            dry_run=False,
            backup=False,
            rebuild_data=bool(fts_rebuild),
        )
        summary["actions"].append("repair_fts_schema_on_recovered_db")
        summary["actions"].append(f"repair_fts_schema_status:{fts_summary.get('status')}")
        if fts_summary.get("status") not in {"OK", "REPAIRED"}:
            summary["recovered_warnings"].append(
                f"fts_repair_failed_or_partial:{fts_summary.get('error')}"
            )

        validation = _validate_recovered_db(recovered_db_path)
        summary["validation_results"] = validation
        summary["table_count_compare"] = _build_table_count_compare(db_path, recovered_db_path)

        quick_ok = bool(validation.get("quick_check", {}).get("ok"))
        tm_ok = bool(validation.get("tm_entry_probe", {}).get("ok"))
        fts_ok = bool(validation.get("fts_status", {}).get("ok"))

        if quick_ok and tm_ok and fts_ok:
            summary["status"] = "SALVAGED_OK"
            if summary["recovered_warnings"]:
                summary["status"] = "SALVAGED_WITH_WARNINGS"
        else:
            summary["status"] = "FAILED"
            summary["error"] = (
                "Recovered DB validation failed: "
                f"quick_check_ok={quick_ok}, tm_entry_probe_ok={tm_ok}, fts_ok={fts_ok}"
            )

        return summary
    except Exception as exc:
        summary["status"] = "FAILED"
        summary["error"] = str(exc)
        return summary
    finally:
        summary["finished_at_utc"] = _utc_now()
        summary["elapsed_s"] = round(time.perf_counter() - started, 3)


def _write_summary(summary: dict[str, Any]) -> Path:
    logs_dir = project_root / "build" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = logs_dir / f"db_corruption_repair_{ts}.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", required=True, help="Path to SQLite database.")
    parser.add_argument(
        "--diagnose-only",
        action="store_true",
        help="Run diagnostics only; do not attempt salvage.",
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="Run PRAGMA integrity_check (slow on large DB).",
    )
    parser.add_argument(
        "--sqlite3-bin",
        default=None,
        help="Optional path to sqlite3 CLI binary for .recover.",
    )
    parser.add_argument(
        "--recovered-db-path",
        default=None,
        help="Optional path for recovered DB output.",
    )
    parser.add_argument(
        "--fts-rebuild",
        action="store_true",
        help="Rebuild FTS data after recovery (can be long on huge DB).",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging.")
    backup_group = parser.add_mutually_exclusive_group()
    backup_group.add_argument("--backup", dest="backup", action="store_true", help="Create backup (default).")
    backup_group.add_argument("--no-backup", dest="backup", action="store_false", help="Skip backup.")
    parser.set_defaults(backup=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    db_path = Path(args.db_path).expanduser()
    if not db_path.exists():
        error = {
            "status": "FAILED",
            "db_path": str(db_path),
            "error": f"Database not found: {db_path}",
        }
        print(json.dumps(error, ensure_ascii=False))
        return 1

    recovered_path = Path(args.recovered_db_path).expanduser() if args.recovered_db_path else None

    summary = repair_db_corruption(
        db_path=db_path,
        deep=bool(args.deep),
        diagnose_only=bool(args.diagnose_only),
        backup=bool(args.backup),
        sqlite3_bin=args.sqlite3_bin,
        recovered_db_path=recovered_path,
        fts_rebuild=bool(args.fts_rebuild),
    )

    summary_path = _write_summary(summary)
    summary["summary_path"] = str(summary_path)
    print(json.dumps(summary, ensure_ascii=False))

    return 0 if summary.get("status") in {"OK", "SALVAGED_OK", "SALVAGED_WITH_WARNINGS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
