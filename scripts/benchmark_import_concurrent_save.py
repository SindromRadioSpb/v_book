"""Benchmark import + concurrent TM save with write-gate tracing."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.db_service import DBService
from app.services.project_exchange.dto import ExportOptions, ImportOptions
from app.services.project_exchange.export_engine import ProjectExportEngine
from app.services.project_exchange.import_engine import ProjectImportEngine
from app.services.translation_admin_service import TranslationAdminService


def _apply_migrations(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        migrations_dir = Path("app/infra/migrations")
        for migration_file in sorted(migrations_dir.glob("*.sql")):
            conn.executescript(migration_file.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def _reset_db_service() -> None:
    try:
        DBService.shutdown()
    except Exception:
        pass
    DBService._instance = None
    DBService._db_manager = None


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


def _backup_sqlite(source_path: Path, dest_path: Path) -> None:
    src_conn = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    dst_conn = sqlite3.connect(str(dest_path))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()


def _validate_sqlite_readable(db_path: Path) -> tuple[bool, str | None]:
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("SELECT 1").fetchone()
            conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        finally:
            conn.close()
        return True, None
    except Exception as exc:
        return False, str(exc)


def _build_source_db(db_path: Path, docs: int, lemmas: int) -> None:
    _apply_migrations(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("INSERT INTO library (library_id, name) VALUES (1, 'Benchmark Source Library')")
        conn.execute(
            """
            INSERT INTO dict_project (project_id, library_id, name, src_lang, tgt_lang, nlp_engine)
            VALUES (1, 1, 'Benchmark Source Project', 'he', 'ru', 'stanza')
            """
        )
        conn.execute("INSERT INTO source_corpus (corpus_id, project_id, name) VALUES (1, 1, 'Benchmark Corpus')")

        for doc_id in range(1, docs + 1):
            conn.execute(
                """
                INSERT INTO source_document (doc_id, corpus_id, file_path, file_name, file_ext, sha256, status)
                VALUES (?, 1, ?, ?, 'txt', ?, 'processed')
                """,
                (
                    doc_id,
                    f"/bench/doc_{doc_id}.txt",
                    f"doc_{doc_id}.txt",
                    f"sha{doc_id:064d}",
                ),
            )
            conn.execute(
                "INSERT INTO document_text (doc_id, raw_text, ocr_used) VALUES (?, ?, 0)",
                (doc_id, f"Benchmark text {doc_id}"),
            )

        for lemma_id in range(1, lemmas + 1):
            conn.execute(
                "INSERT INTO lemma (lemma_id, project_id, lemma_text, pos) VALUES (?, 1, ?, 'NOUN')",
                (lemma_id, f"lemma_{lemma_id:07d}"),
            )

        conn.commit()
    finally:
        conn.close()


def _ensure_probe_tm_entry(target_db_path: Path) -> int:
    conn = sqlite3.connect(str(target_db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        next_library_id = conn.execute(
            "SELECT COALESCE(MAX(library_id), 0) + 1 FROM library"
        ).fetchone()[0]
        next_project_id = conn.execute(
            "SELECT COALESCE(MAX(project_id), 0) + 1 FROM dict_project"
        ).fetchone()[0]
        next_tm_id = conn.execute(
            "SELECT COALESCE(MAX(tm_id), 0) + 1 FROM tm_entry"
        ).fetchone()[0]

        conn.execute(
            "INSERT INTO library (library_id, name) VALUES (?, ?)",
            (next_library_id, f"Benchmark Target Library {next_library_id}"),
        )
        conn.execute(
            """
            INSERT INTO dict_project (project_id, library_id, name, src_lang, tgt_lang, nlp_engine)
            VALUES (?, ?, ?, 'he', 'ru', 'stanza')
            """,
            (next_project_id, next_library_id, f"Benchmark Target Project {next_project_id}"),
        )
        conn.execute(
            """
            INSERT INTO tm_entry (
                tm_id, project_id, kind, src_lang, tgt_lang, src_text, src_norm,
                translation, status, origin
            ) VALUES (?, ?, 'lemma', 'he', 'ru', 'benchmark_probe', 'benchmark_probe', ?, 'approved', 'user_edit')
            """,
            (next_tm_id, next_project_id, "seed_0"),
        )
        conn.commit()
        return int(next_tm_id)
    finally:
        conn.close()


def _parse_gate_trace(trace_path: Path) -> dict[str, Any]:
    if not trace_path.exists():
        return {
            "event_count": 0,
            "max_hold_ms": 0.0,
            "top_holds": [],
            "top_phase_max_holds": [],
        }

    events: list[dict[str, Any]] = []
    with trace_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    hold_events = [event for event in events if event.get("event") == "gate_release" and "hold_ms" in event]
    top_holds = sorted(hold_events, key=lambda item: float(item.get("hold_ms", 0.0)), reverse=True)[:5]

    max_by_phase: dict[str, float] = {}
    for event in hold_events:
        phase = str(event.get("phase", "unknown"))
        hold_ms = float(event.get("hold_ms", 0.0))
        prev = max_by_phase.get(phase, 0.0)
        if hold_ms > prev:
            max_by_phase[phase] = hold_ms

    top_phase_max_holds = [
        {"phase": phase, "max_hold_ms": round(hold_ms, 3)}
        for phase, hold_ms in sorted(max_by_phase.items(), key=lambda item: item[1], reverse=True)[:5]
    ]

    return {
        "event_count": len(events),
        "max_hold_ms": round(max((float(item.get("hold_ms", 0.0)) for item in hold_events), default=0.0), 3),
        "top_holds": top_holds,
        "top_phase_max_holds": top_phase_max_holds,
    }


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    target_db = Path(args.db_path).expanduser()
    if not target_db.exists():
        raise FileNotFoundError(f"Target DB not found: {target_db}")

    logs_dir = Path("build/logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    metrics_path = logs_dir / f"import_concurrent_save_metrics_{run_id}.json"
    save_ops_path = logs_dir / f"import_concurrent_save_ops_{run_id}.jsonl"
    gate_trace_path = logs_dir / f"import_write_gate_trace_{run_id}.jsonl"

    with tempfile.TemporaryDirectory(prefix="hdle_import_bench_") as temp_dir:
        temp_root = Path(temp_dir)
        source_db = temp_root / "source_seed.db"
        bundle_path = temp_root / "bench_bundle.hdleproj"
        target_db_mode = "in_place" if args.use_db_in_place else "copied"
        target_fallback_reason: str | None = None

        if args.use_db_in_place:
            target_work_db = target_db
        else:
            target_work_db = temp_root / "target_work.db"
            _backup_sqlite(target_db, target_work_db)

        target_ok, target_err = _validate_sqlite_readable(target_work_db)
        if not target_ok:
            target_fallback_reason = target_err
            target_work_db = temp_root / "target_fallback.db"
            _apply_migrations(target_work_db)
            target_db_mode = "fresh_migrated_fallback"

        _build_source_db(source_db, docs=args.seed_docs, lemmas=args.seed_lemmas)

        _reset_db_service()
        DBService.initialize(str(source_db))
        export_engine = ProjectExportEngine()
        export_started = time.perf_counter()
        export_report = export_engine.export_project(
            project_id=1,
            out_path=bundle_path,
            options=ExportOptions(),
        )
        export_elapsed = time.perf_counter() - export_started
        if not export_report.success:
            raise RuntimeError(f"Export failed: {export_report.error_message}")

        _reset_db_service()
        probe_tm_id = _ensure_probe_tm_entry(target_work_db)

        _reset_db_service()
        DBService.initialize(str(target_work_db))

        import_engine = ProjectImportEngine()
        translation_service = TranslationAdminService()

        save_ops: list[dict[str, Any]] = []
        save_latencies_ms: list[float] = []
        save_errors: list[str] = []
        busy_errors = 0
        import_in_flight = {"value": True}
        stop_event = threading.Event()

        def save_worker() -> None:
            nonlocal busy_errors
            for attempt in range(1, args.max_save_attempts + 1):
                if stop_event.is_set():
                    break

                loop_started = time.perf_counter()
                started = time.perf_counter()
                ts = time.time()
                try:
                    with DBService.get_instance().get_session() as session:
                        translation_service.update_translation(
                            session,
                            tm_id=probe_tm_id,
                            translation=f"bench_value_{attempt}",
                        )
                    latency_ms = (time.perf_counter() - started) * 1000.0
                    save_latencies_ms.append(latency_ms)
                    save_ops.append(
                        {
                            "ts": ts,
                            "kind": "save_ok",
                            "attempt": attempt,
                            "latency_ms": round(latency_ms, 3),
                            "import_in_flight": bool(import_in_flight["value"]),
                        }
                    )
                except Exception as exc:
                    msg = str(exc)
                    save_errors.append(msg)
                    lowered = msg.lower()
                    if "locked" in lowered or "busy" in lowered or "sqlite_busy" in lowered:
                        busy_errors += 1
                    save_ops.append(
                        {
                            "ts": ts,
                            "kind": "save_error",
                            "attempt": attempt,
                            "error": msg,
                            "import_in_flight": bool(import_in_flight["value"]),
                        }
                    )

                elapsed = time.perf_counter() - loop_started
                sleep_seconds = max(0.0, args.save_cadence_ms / 1000.0 - elapsed)
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)

        progress_events: list[dict[str, Any]] = []

        def progress_callback(stage: str, current: int, total: int) -> None:
            progress_events.append(
                {
                    "ts": time.time(),
                    "stage": stage,
                    "current": int(current),
                    "total": int(total),
                }
            )

        worker_thread = threading.Thread(target=save_worker, name="bench-save-worker", daemon=True)
        worker_thread.start()

        import_started = time.perf_counter()
        import_report = import_engine.import_project(
            bundle_path=bundle_path,
            options=ImportOptions(custom_name=f"Benchmark Imported {run_id}"),
            progress_callback=progress_callback,
            gate_trace_path=gate_trace_path,
        )
        import_elapsed = time.perf_counter() - import_started
        import_in_flight["value"] = False
        stop_event.set()
        worker_thread.join(timeout=30.0)

        with save_ops_path.open("w", encoding="utf-8") as ops_file:
            for event in save_ops:
                ops_file.write(json.dumps(event, ensure_ascii=False) + "\n")

        gate_summary = _parse_gate_trace(gate_trace_path)
        during_import_latencies = [
            float(event["latency_ms"])
            for event in save_ops
            if event.get("kind") == "save_ok" and event.get("import_in_flight")
        ]

        metrics: dict[str, Any] = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "target_db_input": str(target_db),
            "target_db_used": str(target_work_db),
            "target_db_mode": target_db_mode,
            "target_db_fallback_reason": target_fallback_reason,
            "scenario": "import + concurrent save translation",
            "seed": {
                "docs": int(args.seed_docs),
                "lemmas": int(args.seed_lemmas),
                "lemma_batch_size": int(os.environ.get("HDLE_IMPORT_LEMMA_BATCH_SIZE", "2000") or 2000),
                "save_cadence_ms": int(args.save_cadence_ms),
                "max_save_attempts": int(args.max_save_attempts),
            },
            "export": {
                "success": bool(export_report.success),
                "elapsed_s": round(export_elapsed, 3),
            },
            "import": {
                "success": bool(import_report.success),
                "elapsed_s": round(import_elapsed, 3),
                "error_message": import_report.error_message,
                "table_counts": import_report.table_counts,
            },
            "save_ops": {
                "attempts": len(save_ops),
                "success": len([event for event in save_ops if event.get("kind") == "save_ok"]),
                "errors": len(save_errors),
                "busy_errors": busy_errors,
                "latency_ms": {
                    "p50": round(_percentile(save_latencies_ms, 50), 3),
                    "p95": round(_percentile(save_latencies_ms, 95), 3),
                    "max": round(max(save_latencies_ms), 3) if save_latencies_ms else 0.0,
                },
                "latency_during_import_ms": {
                    "p50": round(_percentile(during_import_latencies, 50), 3),
                    "p95": round(_percentile(during_import_latencies, 95), 3),
                    "max": round(max(during_import_latencies), 3) if during_import_latencies else 0.0,
                },
                "count_gt_1000ms": int(sum(1 for value in save_latencies_ms if value > 1000.0)),
                "count_gt_500ms": int(sum(1 for value in save_latencies_ms if value > 500.0)),
                "count_gt_250ms": int(sum(1 for value in save_latencies_ms if value > 250.0)),
            },
            "gate_trace": gate_summary,
            "progress_events_count": len(progress_events),
        }

        metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

        result = {
            "metrics_path": str(metrics_path),
            "ops_path": str(save_ops_path),
            "gate_trace_path": str(gate_trace_path),
            "import_success": metrics["import"]["success"],
            "max_save_latency_ms": metrics["save_ops"]["latency_ms"]["max"],
            "count_gt_1000ms": metrics["save_ops"]["count_gt_1000ms"],
            "top_phase_max_holds": gate_summary.get("top_phase_max_holds", []),
        }
        print(json.dumps(result, ensure_ascii=False))

        _reset_db_service()
        return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", required=True, help="Target hewiki-scale DB path.")
    parser.add_argument(
        "--use-db-in-place",
        action="store_true",
        help="Use target DB directly (mutating). Default is safe copy to temp work DB.",
    )
    parser.add_argument("--seed-docs", type=int, default=6000)
    parser.add_argument("--seed-lemmas", type=int, default=120000)
    parser.add_argument("--save-cadence-ms", type=int, default=100)
    parser.add_argument("--max-save-attempts", type=int, default=100)
    parser.add_argument(
        "--lemma-batch-size",
        type=int,
        default=2000,
        help="Batch size for lemma import phase (500..10000).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    os.environ["HDLE_IMPORT_LEMMA_BATCH_SIZE"] = str(args.lemma_batch_size)
    run_benchmark(args)


if __name__ == "__main__":
    main()
