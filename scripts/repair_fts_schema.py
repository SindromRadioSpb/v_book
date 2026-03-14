#!/usr/bin/env python3
"""Deterministic repair tool for malformed FTS schema entries.

Primary target symptom:
    malformed database schema (sentence_fts) - table sentence_fts already exists
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add project root to path for direct script execution.
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.infra.fts_manager import ensure_fts_tables  # noqa: E402


logger = logging.getLogger(__name__)

FTS_SHADOW_SUFFIXES = ("_data", "_idx", "_content", "_docsize", "_config")
FTS_TABLES = ("sentence_fts", "term_fts")
FTS_TRIGGER_NAMES = (
    "trg_sentence_ai",
    "trg_sentence_ad",
    "trg_sentence_au",
    "trg_term_search_ai",
    "trg_term_search_ad",
    "trg_term_search_au",
)
FTS_BASE_TABLE = {
    "sentence_fts": "document_sentence",
    "term_fts": "term_search",
}
FTS_REBUILD_SQL = {
    "sentence_fts": """
        INSERT INTO sentence_fts(text, doc_id, sentence_id)
        SELECT text, doc_id, sentence_id
        FROM document_sentence
    """,
    "term_fts": """
        INSERT INTO term_fts(he_term, ru_translation, notes, project_id, kind, lemma_id, ngram_id, term_rowid)
        SELECT he_term, ru_translation, notes, project_id, kind, lemma_id, ngram_id, term_rowid
        FROM term_search
    """,
}
FTS_MATCH_PROBES = {
    "sentence_fts": "SELECT sentence_id FROM sentence_fts WHERE sentence_fts MATCH 'test' LIMIT 1",
    "term_fts": "SELECT term_rowid FROM term_fts WHERE term_fts MATCH 'test' LIMIT 1",
}


@dataclass(frozen=True)
class FtsNamespaceSnapshot:
    table: str
    duplicate_names: dict[str, list[int]]
    row_counts: dict[str, int | None]
    probe_errors: dict[str, str]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def _probe_schema_parse_error(conn: sqlite3.Connection) -> str | None:
    try:
        conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        return None
    except sqlite3.DatabaseError as exc:
        return str(exc)


def _fts_namespace_names() -> list[str]:
    names: list[str] = list(FTS_TRIGGER_NAMES)
    for table_name in FTS_TABLES:
        names.append(table_name)
        names.extend(f"{table_name}{suffix}" for suffix in FTS_SHADOW_SUFFIXES)
    return names


def _fetch_duplicate_master_rows_writable(
    conn: sqlite3.Connection,
    *,
    table_name: str,
) -> dict[str, list[int]]:
    names = [table_name] + [f"{table_name}{suffix}" for suffix in FTS_SHADOW_SUFFIXES]
    placeholders = ",".join("?" for _ in names)
    conn.execute("PRAGMA writable_schema=ON")
    try:
        rows = conn.execute(
            f"""
            SELECT name, rowid
            FROM sqlite_master
            WHERE name IN ({placeholders})
            ORDER BY name, rowid
            """,
            names,
        ).fetchall()
    finally:
        conn.execute("PRAGMA writable_schema=OFF")

    by_name: dict[str, list[int]] = {}
    for name, rowid in rows:
        by_name.setdefault(str(name), []).append(int(rowid))
    return {name: ids for name, ids in by_name.items() if len(ids) > 1}


def _fetch_duplicate_master_rows_normal(
    conn: sqlite3.Connection,
    *,
    table_name: str,
) -> dict[str, list[int]]:
    names = [table_name] + [f"{table_name}{suffix}" for suffix in FTS_SHADOW_SUFFIXES]
    placeholders = ",".join("?" for _ in names)
    rows = conn.execute(
        f"""
        SELECT name, GROUP_CONCAT(rowid)
        FROM sqlite_master
        WHERE name IN ({placeholders})
        GROUP BY name
        HAVING COUNT(*) > 1
        """,
        names,
    ).fetchall()
    duplicates: dict[str, list[int]] = {}
    for name, csv_rowids in rows:
        rowids = [int(item) for item in str(csv_rowids).split(",") if item]
        if len(rowids) > 1:
            duplicates[str(name)] = sorted(rowids)
    return duplicates


def _safe_count_query(conn: sqlite3.Connection, sql: str) -> tuple[int | None, str | None]:
    try:
        row = conn.execute(sql).fetchone()
        if row is None:
            return 0, None
        return int(row[0]), None
    except sqlite3.Error as exc:
        return None, str(exc)


def _collect_snapshot(
    conn: sqlite3.Connection,
    table_name: str,
    *,
    use_writable_schema: bool,
    include_base_count: bool,
) -> FtsNamespaceSnapshot:
    probe_errors: dict[str, str] = {}
    row_counts: dict[str, int | None] = {}

    duplicates: dict[str, list[int]] = {}
    try:
        if use_writable_schema:
            duplicates = _fetch_duplicate_master_rows_writable(conn, table_name=table_name)
        else:
            duplicates = _fetch_duplicate_master_rows_normal(conn, table_name=table_name)
    except sqlite3.Error as exc:
        probe_errors[f"duplicate_probe_{table_name}"] = str(exc)

    fts_count, fts_err = _safe_count_query(conn, f"SELECT COUNT(*) FROM {table_name}")
    row_counts[table_name] = fts_count
    if fts_err:
        probe_errors[f"count_{table_name}"] = fts_err

    if include_base_count:
        base_table = FTS_BASE_TABLE[table_name]
        base_count, base_err = _safe_count_query(conn, f"SELECT COUNT(*) FROM {base_table}")
        row_counts[base_table] = base_count
        if base_err:
            probe_errors[f"count_{base_table}"] = base_err

    return FtsNamespaceSnapshot(
        table=table_name,
        duplicate_names=duplicates,
        row_counts=row_counts,
        probe_errors=probe_errors,
    )


def inspect_fts_health(db_path: Path, *, include_base_counts: bool = False) -> dict[str, Any]:
    conn = _connect(db_path)
    try:
        parse_error = _probe_schema_parse_error(conn)
        use_writable_schema = bool(parse_error)

        sentence_snapshot = _collect_snapshot(
            conn,
            "sentence_fts",
            use_writable_schema=use_writable_schema,
            include_base_count=include_base_counts,
        )
        term_snapshot = _collect_snapshot(
            conn,
            "term_fts",
            use_writable_schema=use_writable_schema,
            include_base_count=include_base_counts,
        )

        trigger_names: list[str] = []
        try:
            if use_writable_schema:
                conn.execute("PRAGMA writable_schema=ON")
            try:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger' AND name IN (?, ?, ?, ?, ?, ?)",
                    FTS_TRIGGER_NAMES,
                ).fetchall()
            finally:
                if use_writable_schema:
                    conn.execute("PRAGMA writable_schema=OFF")
            trigger_names = sorted(str(row[0]) for row in rows)
        except sqlite3.Error as exc:
            sentence_snapshot.probe_errors["trigger_probe"] = str(exc)

        missing_triggers = sorted(set(FTS_TRIGGER_NAMES) - set(trigger_names))

        duplicate_names: dict[str, list[int]] = {}
        duplicate_names.update(sentence_snapshot.duplicate_names)
        duplicate_names.update(term_snapshot.duplicate_names)

        issues: list[str] = []
        if parse_error:
            issues.append(f"schema_parse_error: {parse_error}")
        if duplicate_names:
            for name, rowids in sorted(duplicate_names.items()):
                issues.append(f"duplicate_sqlite_master_entry: {name} rowids={rowids}")
        if missing_triggers:
            issues.append(f"missing_triggers: {missing_triggers}")
        for key, value in sentence_snapshot.probe_errors.items():
            issues.append(f"probe_error:{key}: {value}")
        for key, value in term_snapshot.probe_errors.items():
            issues.append(f"probe_error:{key}: {value}")
        if include_base_counts:
            sentence_fts_count = sentence_snapshot.row_counts.get("sentence_fts")
            document_sentence_count = sentence_snapshot.row_counts.get("document_sentence")
            if (
                sentence_fts_count is not None
                and document_sentence_count is not None
                and sentence_fts_count != document_sentence_count
            ):
                issues.append(
                    "sentence_fts_row_mismatch: "
                    f"sentence_fts={sentence_fts_count}, "
                    f"document_sentence={document_sentence_count}"
                )

            term_fts_count = term_snapshot.row_counts.get("term_fts")
            term_search_count = term_snapshot.row_counts.get("term_search")
            if (
                term_fts_count is not None
                and term_search_count is not None
                and term_fts_count != term_search_count
            ):
                issues.append(
                    "term_fts_row_mismatch: "
                    f"term_fts={term_fts_count}, term_search={term_search_count}"
                )

        return {
            "schema_parse_error": parse_error,
            "issues": issues,
            "duplicate_names": duplicate_names,
            "missing_triggers": missing_triggers,
            "counts": {
                **sentence_snapshot.row_counts,
                **term_snapshot.row_counts,
            },
            "trigger_names": trigger_names,
        }
    finally:
        conn.close()


def _create_backup(db_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.with_name(f"{db_path.stem}.fts_repair_{timestamp}{db_path.suffix}.bak")
    logger.info("Creating backup: %s", backup_path)
    shutil.copy2(db_path, backup_path)
    return backup_path


def _remove_duplicate_master_rows(
    conn: sqlite3.Connection,
    duplicate_names: dict[str, list[int]],
) -> dict[str, list[int]]:
    deleted: dict[str, list[int]] = {}
    if not duplicate_names:
        return deleted

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("PRAGMA writable_schema=ON")
        for name, rowids in sorted(duplicate_names.items()):
            keep_rowid = min(rowids)
            drop_rowids = [rowid for rowid in rowids if rowid != keep_rowid]
            for rowid in drop_rowids:
                conn.execute("DELETE FROM sqlite_master WHERE rowid=?", (int(rowid),))
            if drop_rowids:
                deleted[name] = drop_rowids
        conn.execute("PRAGMA writable_schema=OFF")

        current_schema_version = int(conn.execute("PRAGMA schema_version").fetchone()[0])
        conn.execute(f"PRAGMA schema_version={current_schema_version + 1}")
        conn.commit()
    except Exception:
        try:
            conn.execute("PRAGMA writable_schema=OFF")
        except Exception:
            pass
        conn.rollback()
        raise

    return deleted


def _hard_reset_fts_namespace(conn: sqlite3.Connection) -> int:
    names = _fts_namespace_names()
    placeholders = ",".join("?" for _ in names)

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("PRAGMA writable_schema=ON")
        cursor = conn.execute(
            f"DELETE FROM sqlite_master WHERE name IN ({placeholders})",
            names,
        )
        deleted_rows = int(cursor.rowcount if cursor.rowcount is not None else 0)
        conn.execute("PRAGMA writable_schema=OFF")

        current_schema_version = int(conn.execute("PRAGMA schema_version").fetchone()[0])
        conn.execute(f"PRAGMA schema_version={current_schema_version + 1}")
        conn.commit()
        return deleted_rows
    except Exception:
        try:
            conn.execute("PRAGMA writable_schema=OFF")
        except Exception:
            pass
        conn.rollback()
        raise


def _drop_fts_objects(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        for trigger_name in FTS_TRIGGER_NAMES:
            conn.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
        for table_name in FTS_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _create_fts_objects(conn: sqlite3.Connection) -> None:
    ensure_fts_tables(conn, schema="main", rebuild=False)


def _rebuild_fts_table(conn: sqlite3.Connection, table_name: str) -> str | None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(f"DELETE FROM {table_name}")
        conn.execute(FTS_REBUILD_SQL[table_name])
        conn.commit()
        return None
    except sqlite3.Error as exc:
        conn.rollback()
        return str(exc)


def _validate_repaired_fts(
    conn: sqlite3.Connection,
    *,
    require_sentence_count_match: bool,
    require_term_count_match: bool,
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    details: dict[str, Any] = {}

    parse_error = _probe_schema_parse_error(conn)
    if parse_error:
        errors.append(f"schema_parse_error_after_repair: {parse_error}")

    duplicate_names: dict[str, list[int]] = {}
    for table_name in FTS_TABLES:
        try:
            duplicate_names.update(_fetch_duplicate_master_rows_normal(conn, table_name=table_name))
        except sqlite3.Error as exc:
            errors.append(f"duplicate_probe_failed_after_repair_{table_name}: {exc}")

    if duplicate_names:
        errors.append(f"duplicate_sqlite_master_entries_after_repair: {duplicate_names}")

    trigger_names = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name IN (?, ?, ?, ?, ?, ?)",
            FTS_TRIGGER_NAMES,
        ).fetchall()
    }
    missing_triggers = sorted(set(FTS_TRIGGER_NAMES) - trigger_names)
    if missing_triggers:
        errors.append(f"missing_triggers_after_repair: {missing_triggers}")

    sentence_count, sentence_err = _safe_count_query(conn, "SELECT COUNT(*) FROM sentence_fts")
    term_count, term_err = _safe_count_query(conn, "SELECT COUNT(*) FROM term_fts")
    details["counts"] = {
        "sentence_fts": sentence_count,
        "term_fts": term_count,
    }

    if sentence_err:
        errors.append(f"sentence_fts_count_error_after_repair: {sentence_err}")
    if term_err:
        errors.append(f"term_fts_count_error_after_repair: {term_err}")

    if require_sentence_count_match:
        doc_sentence_count, doc_sentence_err = _safe_count_query(conn, "SELECT COUNT(*) FROM document_sentence")
        details["counts"]["document_sentence"] = doc_sentence_count
        if doc_sentence_err:
            errors.append(f"document_sentence_count_error_after_repair: {doc_sentence_err}")
        elif sentence_count is not None and doc_sentence_count is not None and sentence_count != doc_sentence_count:
            errors.append(
                "sentence_fts_row_mismatch_after_repair: "
                f"sentence_fts={sentence_count}, document_sentence={doc_sentence_count}"
            )

    if require_term_count_match:
        term_search_count, term_search_err = _safe_count_query(conn, "SELECT COUNT(*) FROM term_search")
        details["counts"]["term_search"] = term_search_count
        if term_search_err:
            errors.append(f"term_search_count_error_after_repair: {term_search_err}")
        elif term_count is not None and term_search_count is not None and term_count != term_search_count:
            errors.append(
                "term_fts_row_mismatch_after_repair: "
                f"term_fts={term_count}, term_search={term_search_count}"
            )

    try:
        conn.execute(FTS_MATCH_PROBES["sentence_fts"]).fetchall()
    except sqlite3.Error as exc:
        errors.append(f"sentence_fts_match_probe_failed: {exc}")

    try:
        conn.execute(FTS_MATCH_PROBES["term_fts"]).fetchall()
    except sqlite3.Error as exc:
        errors.append(f"term_fts_match_probe_failed: {exc}")

    details["duplicate_names"] = duplicate_names
    details["missing_triggers"] = missing_triggers
    details["parse_error"] = parse_error
    return errors, details


def repair_fts_schema(
    *,
    db_path: Path,
    dry_run: bool = False,
    backup: bool = True,
    rebuild_data: bool = True,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    started_utc = _utc_now()
    summary: dict[str, Any] = {
        "status": "FAILED",
        "started_at_utc": started_utc,
        "db_path": str(db_path),
        "dry_run": bool(dry_run),
        "backup_enabled": bool(backup),
        "rebuild_data": bool(rebuild_data),
        "backup_path": None,
        "issues_detected": [],
        "actions": [],
        "warnings": [],
        "before": {},
        "after": {},
        "error": None,
    }

    try:
        before = inspect_fts_health(db_path, include_base_counts=True)
        summary["before"] = before
        issues = list(before.get("issues", []))
        summary["issues_detected"] = issues

        if not issues:
            summary["status"] = "OK"
            return summary

        if dry_run:
            summary["status"] = "FAILED"
            summary["error"] = "Repair required but dry-run mode does not apply changes"
            return summary

        if backup:
            backup_path = _create_backup(db_path)
            summary["backup_path"] = str(backup_path)
            summary["actions"].append(f"backup_created:{backup_path}")

        conn = _connect(db_path)
        try:
            duplicate_names = dict(before.get("duplicate_names", {}))
            if duplicate_names:
                deleted = _remove_duplicate_master_rows(conn, duplicate_names)
                summary["actions"].append(f"deleted_duplicate_sqlite_master_rows:{deleted}")
            else:
                summary["actions"].append("no_duplicate_sqlite_master_rows_to_delete")
        finally:
            conn.close()

        conn = _connect(db_path)
        try:
            try:
                _drop_fts_objects(conn)
                summary["actions"].append("dropped_existing_fts_tables_and_triggers")
            except sqlite3.Error as drop_exc:
                summary["warnings"].append(f"drop_fts_objects_failed:{drop_exc}")
                removed_rows = _hard_reset_fts_namespace(conn)
                summary["actions"].append(f"hard_reset_fts_namespace_sqlite_master:{removed_rows}")
        finally:
            conn.close()

        conn = _connect(db_path)
        try:
            _create_fts_objects(conn)
            summary["actions"].append("recreated_fts_tables_and_triggers")

            sentence_rebuild_ok = False
            term_rebuild_ok = False
            if rebuild_data:
                sentence_rebuild_err = _rebuild_fts_table(conn, "sentence_fts")
                if sentence_rebuild_err is None:
                    sentence_rebuild_ok = True
                    summary["actions"].append("rebuild_sentence_fts_completed")
                else:
                    summary["warnings"].append(f"rebuild_sentence_fts_failed:{sentence_rebuild_err}")

                term_rebuild_err = _rebuild_fts_table(conn, "term_fts")
                if term_rebuild_err is None:
                    term_rebuild_ok = True
                    summary["actions"].append("rebuild_term_fts_completed")
                else:
                    summary["warnings"].append(f"rebuild_term_fts_failed:{term_rebuild_err}")
            else:
                summary["actions"].append("fts_rebuild_skipped_by_flag")

            for table_name in FTS_TABLES:
                try:
                    conn.execute(f"INSERT INTO {table_name}({table_name}) VALUES('optimize')")
                    conn.commit()
                    summary["actions"].append(f"fts_optimize_completed:{table_name}")
                except sqlite3.Error as opt_exc:
                    conn.rollback()
                    summary["warnings"].append(f"fts_optimize_skipped:{table_name}:{opt_exc}")

            validation_errors, validation_details = _validate_repaired_fts(
                conn,
                require_sentence_count_match=sentence_rebuild_ok,
                require_term_count_match=term_rebuild_ok,
            )
            summary["after"] = validation_details
            if validation_errors:
                summary["error"] = "; ".join(validation_errors)
                summary["status"] = "FAILED"
            else:
                summary["status"] = "REPAIRED"
        finally:
            conn.close()

        if summary["status"] != "FAILED":
            after = inspect_fts_health(db_path, include_base_counts=True)
            summary["after"] = {
                **summary.get("after", {}),
                "post_inspection": after,
            }
            if after.get("issues"):
                summary["status"] = "FAILED"
                summary["error"] = f"Post-inspection issues remain: {after['issues']}"

        return summary
    except Exception as exc:
        summary["status"] = "FAILED"
        summary["error"] = str(exc)
        return summary
    finally:
        elapsed_s = time.perf_counter() - started_at
        summary["finished_at_utc"] = _utc_now()
        summary["elapsed_s"] = round(elapsed_s, 3)


def _write_summary(summary: dict[str, Any]) -> Path:
    logs_dir = project_root / "build" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = logs_dir / f"fts_repair_{ts}.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", required=True, help="Path to SQLite database.")
    parser.add_argument("--dry-run", action="store_true", help="Only inspect, do not modify DB.")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging.")
    parser.add_argument(
        "--skip-rebuild",
        action="store_true",
        help="Skip FTS data repopulation; repair schema objects only.",
    )
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

    summary = repair_fts_schema(
        db_path=db_path,
        dry_run=bool(args.dry_run),
        backup=bool(args.backup),
        rebuild_data=not bool(args.skip_rebuild),
    )
    out_path = _write_summary(summary)
    summary["summary_path"] = str(out_path)
    print(json.dumps(summary, ensure_ascii=False))

    return 0 if summary.get("status") in {"OK", "REPAIRED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
