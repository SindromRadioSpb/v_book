
#!/usr/bin/env python3
"""PATCH-05: Real pipeline benchmark harness (sandbox-only, deterministic)."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
import sys
import tempfile
import time
import traceback
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LOG = logging.getLogger("pipeline_bench")

DEFAULT_PHONIKUD_MODEL_PATH = r"M:\V_book\HDLE_Processing\models\phonikud-1.0.int8.onnx"
DEFAULT_GCT_KEY_PATH = r"J:\Project_Vibe\V_book -info files\api_key_Google_translait"
DEFAULT_GCTTS_KEY_PATH = r"J:\Project_Vibe\V_book -info files\api_key_Google_tts"
DEFAULT_SOURCE_DB = (
    r"J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db"
)
DEFAULT_SANDBOX_DB = r"J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_sandbox.db"
DEFAULT_PROJECT_NAME = "BENCH_PIPELINE"
DEFAULT_BENCH_PREFIX = "BENCH_"
DEFAULT_TEMP_ROOT = r"J:\Project_Vibe\V_book\build\tmp\pipeline_bench_work"
BENCH_TIER_PRESETS: dict[str, dict[str, Any]] = {
    "smoke": {
        "doc_limit": 30,
        "recommended_wall_budget_sec": 300,
        "description": "Small validation slice for quick repeated checks.",
    },
    "medium": {
        "doc_limit": 1000,
        "recommended_wall_budget_sec": 600,
        "description": "Completed large bounded slice validated on this machine.",
    },
    "large": {
        "doc_limit": 2000,
        "recommended_wall_budget_sec": 900,
        "description": "In-place sandbox tier with reusable working DB.",
    },
    "ceiling": {
        "doc_limit": 6000,
        "recommended_wall_budget_sec": 1800,
        "description": "Reference ceiling tier; may still exceed local wall budget.",
    },
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def deterministic_slice_doc_ids(doc_ids: list[int], limit: int) -> list[int]:
    """Sorted deterministic subset helper (used by tests and runtime)."""
    unique_sorted = sorted({int(v) for v in doc_ids})
    if limit <= 0:
        return unique_sorted
    return unique_sorted[:limit]


def build_artifact_file_paths(output_dir: Path) -> dict[str, Path]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = _utc_now().strftime("%Y%m%d_%H%M%S")
    return {
        "timestamp": Path(ts),
        "latest_log": output_dir / "pipeline_bench_latest.log",
        "metrics_json": output_dir / f"pipeline_bench_metrics_{ts}.json",
        "report_md": output_dir / f"pipeline_bench_report_{ts}.md",
    }


def _is_forbidden_m_path(path: Path) -> bool:
    normalized = str(path.resolve()).replace("/", "\\").upper()
    return normalized.startswith("M:\\")


def _is_expected_j_path(path: Path) -> bool:
    normalized = str(path.resolve()).replace("/", "\\").upper()
    return normalized.startswith("J:\\")


def _sqlite_backup(source_path: Path, dest_path: Path) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    dst_conn = sqlite3.connect(str(dest_path))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()


def _sqlite_sidecar_paths(db_path: Path) -> dict[str, Path]:
    return {
        "wal": Path(f"{db_path}-wal"),
        "shm": Path(f"{db_path}-shm"),
        "journal": Path(f"{db_path}-journal"),
    }


def _collect_sidecar_sizes(db_path: Path) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for name, path in _sqlite_sidecar_paths(db_path).items():
        if path.exists():
            try:
                sizes[name] = int(path.stat().st_size)
            except OSError:
                sizes[name] = -1
    return sizes


def _remove_sqlite_sidecars(db_path: Path) -> dict[str, int]:
    removed: dict[str, int] = {}
    for name, path in _sqlite_sidecar_paths(db_path).items():
        if not path.exists():
            continue
        try:
            removed[name] = int(path.stat().st_size)
        except OSError:
            removed[name] = -1
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            LOG.warning("Failed to remove sidecar %s: %s", path, exc)
    return removed


def _checkpoint_sqlite_wal(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "db_path": str(db_path),
            "before": {},
            "after": {},
            "checkpoint_result": None,
        }

    before = _collect_sidecar_sizes(db_path)
    checkpoint_result = None
    conn = sqlite3.connect(str(db_path), timeout=60)
    try:
        conn.execute("PRAGMA busy_timeout=60000")
        checkpoint_row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint_row is not None:
            checkpoint_result = [int(value) for value in checkpoint_row]
    finally:
        conn.close()

    # Best-effort cleanup for empty leftovers after a successful checkpoint.
    for path in _sqlite_sidecar_paths(db_path).values():
        try:
            if path.exists() and path.stat().st_size == 0:
                path.unlink(missing_ok=True)
        except OSError:
            pass

    return {
        "db_path": str(db_path),
        "before": before,
        "after": _collect_sidecar_sizes(db_path),
        "checkpoint_result": checkpoint_result,
    }


def _reset_db_service() -> None:
    from app.services.db_service import DBService

    try:
        DBService.shutdown()
    except Exception:
        pass
    DBService._instance = None
    DBService._db_manager = None


def _setup_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    for handler in list(LOG.handlers):
        LOG.removeHandler(handler)
    LOG.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    LOG.addHandler(file_handler)
    LOG.addHandler(stream_handler)


def _cleanup_temp_root(temp_root: Path) -> None:
    """Best-effort cleanup of stale temp run directories from prior aborted runs."""
    if not temp_root.exists():
        return
    for child in sorted(temp_root.iterdir(), key=lambda p: p.name):
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        except Exception as exc:
            LOG.warning("Temp cleanup skipped for %s: %s", child, exc)


def _resolve_json_path(raw_path: str, label: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    if path.is_file():
        return path
    if path.is_dir():
        candidates = sorted(path.glob("*.json"))
        if candidates:
            return candidates[0].resolve()
    raise FileNotFoundError(
        f"{label} path is invalid: expected JSON file or folder with *.json -> {path}"
    )


def _load_build_meta() -> dict[str, Any]:
    try:
        from app import build_meta

        return {
            "app_version": getattr(build_meta, "APP_VERSION", "unknown"),
            "build_commit": getattr(build_meta, "BUILD_COMMIT", "unknown"),
            "build_dirty": getattr(build_meta, "BUILD_DIRTY", 0),
            "build_time_utc": getattr(build_meta, "BUILD_TIME_UTC", "unknown"),
        }
    except Exception:
        return {
            "app_version": "unknown",
            "build_commit": "unknown",
            "build_dirty": 0,
            "build_time_utc": "unknown",
        }


def _validate_runtime_contract(args: argparse.Namespace) -> None:
    db_path = Path(args.db_path).expanduser().resolve()
    source_db_raw = getattr(args, "source_db", None)
    source_db = Path(source_db_raw).expanduser().resolve() if source_db_raw else None
    temp_root_raw = getattr(args, "temp_root", DEFAULT_TEMP_ROOT)
    temp_root = Path(temp_root_raw).expanduser().resolve()

    if _is_forbidden_m_path(db_path):
        raise ValueError(f"Forbidden --db-path on M: drive: {db_path}")
    if source_db is not None and _is_forbidden_m_path(source_db):
        raise ValueError(f"Forbidden --source-db on M: drive: {source_db}")
    if _is_forbidden_m_path(temp_root):
        raise ValueError(f"Forbidden --temp-root on M: drive: {temp_root}")
    if not args.copy_target:
        raise ValueError("--copy-target is mandatory for all scenarios")
    if not _is_expected_j_path(db_path):
        raise ValueError(f"--db-path must be on J: drive for sandbox safety: {db_path}")
    if source_db is not None and not _is_expected_j_path(source_db):
        raise ValueError(f"--source-db must be on J: drive for sandbox safety: {source_db}")
    if not _is_expected_j_path(temp_root):
        raise ValueError(f"--temp-root must be on J: drive for sandbox safety: {temp_root}")
    if source_db is not None and db_path == source_db:
        raise ValueError("--db-path must differ from --source-db for sandbox safety")
    if args.scenario == "cleanup_sandbox":
        if not db_path.exists():
            raise FileNotFoundError(f"--db-path not found for cleanup: {db_path}")
        cleanup_project_name = str(getattr(args, "cleanup_project_name", "") or "").strip()
        cleanup_prefix = str(getattr(args, "cleanup_prefix", DEFAULT_BENCH_PREFIX) or "").strip()
        if not cleanup_project_name and not cleanup_prefix:
            raise ValueError("cleanup requires --cleanup-project-name or --cleanup-prefix")
        if cleanup_project_name and cleanup_prefix and not cleanup_project_name.startswith(cleanup_prefix):
            raise ValueError("--cleanup-project-name must start with --cleanup-prefix for safety")
        return
    if args.scenario == "reset_sandbox":
        if source_db is None or not source_db.exists():
            raise FileNotFoundError(f"--source-db not found: {source_db}")
        return
    if source_db is None or not source_db.exists():
        raise FileNotFoundError(f"--source-db not found: {source_db}")
    if bool(getattr(args, "pre_reset_sandbox", False)) and not bool(
        getattr(args, "reuse_working_db", False)
    ):
        raise ValueError("--pre-reset-sandbox requires --reuse-working-db")
    if bool(getattr(args, "post_cleanup_bench", False)) and not bool(
        getattr(args, "reuse_working_db", False)
    ):
        raise ValueError("--post-cleanup-bench requires --reuse-working-db")
    bench_project_name = str(getattr(args, "bench_project_name", "") or "").strip()
    if bool(getattr(args, "post_cleanup_bench", False)) and not bench_project_name.startswith(
        DEFAULT_BENCH_PREFIX
    ):
        raise ValueError(
            f"--post-cleanup-bench requires --bench-project-name to start with {DEFAULT_BENCH_PREFIX!r}"
        )
    if args.doc_limit <= 0:
        raise ValueError("--doc-limit must be > 0")
    if args.lemma_limit <= 0 or args.term_limit <= 0 or args.sentence_limit <= 0:
        raise ValueError("--lemma-limit/--term-limit/--sentence-limit must be > 0")


def resolve_tier_preset(args: argparse.Namespace, raw_argv: list[str] | None = None) -> dict[str, Any]:
    """Resolve optional benchmark tier without breaking explicit CLI overrides."""
    tier_name = str(getattr(args, "tier", "") or "").strip().lower()
    if not tier_name:
        return {
            "name": None,
            "doc_limit": int(getattr(args, "doc_limit", 0) or 0),
            "recommended_wall_budget_sec": None,
            "description": "",
        }

    preset = BENCH_TIER_PRESETS[tier_name]
    raw_argv = raw_argv or []
    explicit_doc_limit = any(str(part).startswith("--doc-limit") for part in raw_argv)
    if not explicit_doc_limit:
        args.doc_limit = int(preset["doc_limit"])

    return {
        "name": tier_name,
        "doc_limit": int(args.doc_limit),
        "recommended_wall_budget_sec": int(preset["recommended_wall_budget_sec"]),
        "description": str(preset["description"]),
    }


def _run_cleanup_sandbox(
    session,
    *,
    cleanup_project_name: str | None,
    cleanup_prefix: str,
) -> dict[str, Any]:
    from sqlalchemy import select
    from app.infra.sa_models import DictProject
    from app.services.project_service import ProjectService

    started = _utc_now().isoformat()
    t0 = time.perf_counter()

    stmt = select(DictProject.project_id, DictProject.name).order_by(DictProject.project_id.asc())
    if cleanup_project_name:
        stmt = stmt.where(DictProject.name == cleanup_project_name)
    else:
        stmt = stmt.where(DictProject.name.like(f"{cleanup_prefix}%"))

    matches = session.execute(stmt).all()
    deleted_projects: list[dict[str, Any]] = []
    service = ProjectService()
    for project_id, project_name in matches:
        delete_report = service.delete_project(session, int(project_id))
        if not delete_report.success:
            raise RuntimeError(
                f"Cleanup failed for project {project_name} ({project_id}): "
                f"{delete_report.error_message or 'unknown error'}"
            )
        deleted_projects.append(
            {
                "project_id": int(project_id),
                "name": project_name,
            }
        )

    return {
        "name": "cleanup_sandbox",
        "started_at_utc": started,
        "ended_at_utc": _utc_now().isoformat(),
        "duration_sec": round(time.perf_counter() - t0, 3),
        "rows_processed": {"lemma": 0, "term": 0, "sentence": 0},
        "errors_count": 0,
        "error_samples": [],
        "details": {
            "deleted_count": len(deleted_projects),
            "deleted_projects": deleted_projects,
            "cleanup_project_name": cleanup_project_name,
            "cleanup_prefix": cleanup_prefix,
        },
    }


def _run_reset_sandbox(
    *,
    base_db: Path,
    source_db: Path,
    duration_sec: float,
) -> dict[str, Any]:
    """Build result payload for sandbox reset."""
    return {
        "name": "reset_sandbox",
        "started_at_utc": _utc_now().isoformat(),
        "ended_at_utc": _utc_now().isoformat(),
        "duration_sec": round(float(duration_sec), 3),
        "rows_processed": {"lemma": 0, "term": 0, "sentence": 0},
        "errors_count": 0,
        "error_samples": [],
        "details": {
            "source_db": str(source_db),
            "target_db": str(base_db),
            "size_bytes": int(base_db.stat().st_size) if base_db.exists() else 0,
        },
    }


def _record_cycle_action(
    report: dict[str, Any],
    *,
    name: str,
    status: str,
    duration_sec: float,
    details: dict[str, Any],
) -> None:
    actions = report.setdefault("maintenance_cycle", {}).setdefault("actions", [])
    actions.append(
        {
            "name": name,
            "status": status,
            "duration_sec": round(float(duration_sec), 3),
            "details": details,
        }
    )


def _configure_google_cloud_translate(key_path: Path) -> None:
    from app.infra.settings import SettingsService
    from app.infra.translators.local_providers_setup import register_google_cloud_translate

    settings = SettingsService.get_instance()
    settings.set_value("mt/providers/google_cloud_translate/enabled", True)
    settings.set_value("mt/providers/google_cloud_translate/auth_mode", "service_account_json")
    settings.set_value("mt/providers/google_cloud_translate/service_account_path", str(key_path))
    settings.set_value("mt/providers/google_cloud_translate/service_account_credential_id", "")
    settings.sync()
    if not register_google_cloud_translate():
        raise RuntimeError("Failed to register google_cloud_translate provider")


def _configure_google_cloud_tts(key_path: Path) -> None:
    from app.infra.settings import SettingsService
    from app.infra.audio.local_providers_setup import register_default_audio_providers

    settings = SettingsService.get_instance()
    settings.set_value("audio/providers/google_cloud_tts/enabled", True)
    settings.set_value("audio/providers/google_cloud_tts/auth_mode", "service_account_json")
    settings.set_value("audio/providers/google_cloud_tts/service_account_path", str(key_path))
    settings.set_value("audio/providers/google_cloud_tts/service_account_credential_id", "")
    settings.sync()
    register_default_audio_providers()


def _prepare_base_sandbox(base_db: Path, source_db: Path, *, reuse_existing: bool = False) -> bool:
    base_db.parent.mkdir(parents=True, exist_ok=True)
    if reuse_existing and base_db.exists() and base_db.is_file():
        _checkpoint_sqlite_wal(base_db)
        return False
    temp_target = base_db.with_name(f"{base_db.name}.reset_tmp")
    if temp_target.exists():
        temp_target.unlink(missing_ok=True)
    _remove_sqlite_sidecars(temp_target)
    # Refresh canonical sandbox base from local writable corpus copy.
    _sqlite_backup(source_db, temp_target)
    _remove_sqlite_sidecars(base_db)
    if base_db.exists():
        base_db.unlink(missing_ok=True)
    temp_target.replace(base_db)
    _remove_sqlite_sidecars(base_db)
    return True


@contextmanager
def _working_db_copy(base_db: Path, temp_root: Path):
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="hdle_pipeline_bench_",
        dir=str(temp_root),
        ignore_cleanup_errors=True,
    ) as temp_dir:
        run_db = Path(temp_dir) / "pipeline_work.db"
        t0 = time.perf_counter()
        _sqlite_backup(base_db, run_db)
        yield run_db, round(time.perf_counter() - t0, 3)


def _select_source_doc_ids(session, source_project_id: int, doc_limit: int) -> list[int]:
    from sqlalchemy import select
    from app.infra.sa_models import SourceCorpus, SourceDocument

    source_doc_ids = (
        session.execute(
            select(SourceDocument.doc_id)
            .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
            .where(SourceCorpus.project_id == source_project_id)
            .order_by(SourceDocument.doc_id.asc())
        )
        .scalars()
        .all()
    )
    return deterministic_slice_doc_ids(list(source_doc_ids), doc_limit)

def _clone_slice_into_bench_project(
    session,
    *,
    source_project_id: int,
    bench_project_name: str,
    doc_limit: int,
) -> dict[str, Any]:
    from sqlalchemy import select
    from app.infra.sa_models import (
        DictProject,
        DocumentSentence,
        DocumentText,
        Lemma,
        LemmaDocStat,
        LemmaProjectStat,
        SourceCorpus,
        SourceDocument,
    )

    source_project = session.get(DictProject, source_project_id)
    if source_project is None:
        raise ValueError(f"Source project not found: {source_project_id}")

    selected_source_doc_ids = _select_source_doc_ids(session, source_project_id, doc_limit)
    if not selected_source_doc_ids:
        raise RuntimeError(f"No documents available for source project_id={source_project_id}")

    existing_bench = session.execute(
        select(DictProject)
        .where(
            DictProject.library_id == source_project.library_id,
            DictProject.name == bench_project_name,
        )
        .limit(1)
    ).scalar_one_or_none()
    if existing_bench is not None:
        session.delete(existing_bench)
        session.flush()

    bench_project = DictProject(
        library_id=source_project.library_id,
        name=bench_project_name,
        description=f"Deterministic benchmark slice from project_id={source_project_id}",
        src_lang=source_project.src_lang,
        tgt_lang=source_project.tgt_lang,
        nlp_engine=source_project.nlp_engine,
        nlp_engine_version=source_project.nlp_engine_version,
        mwe_min_freq=source_project.mwe_min_freq,
        mwe_min_pmi=source_project.mwe_min_pmi,
        mwe_min_tscore=source_project.mwe_min_tscore,
        mwe_max_n=source_project.mwe_max_n,
        is_general_corpus=0,
        general_corpus_id=None,
    )
    session.add(bench_project)
    session.flush()

    bench_corpus = SourceCorpus(
        project_id=bench_project.project_id,
        name=f"{bench_project_name}_CORPUS",
        description="Generated by scripts/benchmarks/bench_reference_pipeline.py",
    )
    session.add(bench_corpus)
    session.flush()

    source_docs = (
        session.execute(
            select(SourceDocument)
            .where(SourceDocument.doc_id.in_(selected_source_doc_ids))
            .order_by(SourceDocument.doc_id.asc())
        )
        .scalars()
        .all()
    )

    doc_id_map: dict[int, int] = {}
    for row in source_docs:
        copied = SourceDocument(
            corpus_id=bench_corpus.corpus_id,
            file_path=row.file_path,
            file_name=row.file_name,
            file_ext=row.file_ext,
            file_size_bytes=row.file_size_bytes,
            sha256=row.sha256,
            imported_at=row.imported_at,
            processed_at=row.processed_at,
            file_mtime_utc=row.file_mtime_utc,
            status=row.status,
            error_message=row.error_message,
            sentence_count=row.sentence_count,
            token_count=row.token_count,
            tag=row.tag,
            link_url=row.link_url,
            level=row.level,
            topic=row.topic,
        )
        session.add(copied)
        session.flush()
        doc_id_map[int(row.doc_id)] = int(copied.doc_id)

    source_texts = (
        session.execute(
            select(DocumentText)
            .where(DocumentText.doc_id.in_(selected_source_doc_ids))
            .order_by(DocumentText.doc_id.asc())
        )
        .scalars()
        .all()
    )
    for row in source_texts:
        mapped_doc_id = doc_id_map.get(int(row.doc_id))
        if mapped_doc_id is None:
            continue
        session.add(
            DocumentText(
                doc_id=mapped_doc_id,
                raw_text=row.raw_text,
                cleaned_text=row.cleaned_text,
                ocr_used=row.ocr_used,
            )
        )

    sentence_id_map: dict[int, int] = {}
    source_sentences = (
        session.execute(
            select(DocumentSentence)
            .where(DocumentSentence.doc_id.in_(selected_source_doc_ids))
            .order_by(
                DocumentSentence.doc_id.asc(),
                DocumentSentence.sent_index.asc(),
                DocumentSentence.sentence_id.asc(),
            )
        )
        .scalars()
        .all()
    )
    for row in source_sentences:
        mapped_doc_id = doc_id_map.get(int(row.doc_id))
        if mapped_doc_id is None:
            continue
        copied = DocumentSentence(
            doc_id=mapped_doc_id,
            sent_index=row.sent_index,
            text=row.text,
        )
        session.add(copied)
        session.flush()
        sentence_id_map[int(row.sentence_id)] = int(copied.sentence_id)

    lemma_id_map: dict[int, int] = {}
    source_lemmas = (
        session.execute(
            select(Lemma)
            .join(LemmaDocStat, LemmaDocStat.lemma_id == Lemma.lemma_id)
            .where(
                Lemma.project_id == source_project_id,
                LemmaDocStat.project_id == source_project_id,
                LemmaDocStat.doc_id.in_(selected_source_doc_ids),
            )
            .distinct()
            .order_by(Lemma.lemma_id.asc())
        )
        .scalars()
        .all()
    )
    for row in source_lemmas:
        copied = Lemma(
            project_id=bench_project.project_id,
            lemma_text=row.lemma_text,
            pos=row.pos,
            morph_json=row.morph_json,
            created_at=row.created_at,
            entity_class=row.entity_class,
            is_noise=row.is_noise,
            noise_reason=row.noise_reason,
            norm_text=row.norm_text,
        )
        session.add(copied)
        session.flush()
        lemma_id_map[int(row.lemma_id)] = int(copied.lemma_id)

    copied_lemma_doc_stats = 0
    if lemma_id_map:
        source_lemma_stats = (
            session.execute(
                select(LemmaDocStat)
                .where(
                    LemmaDocStat.project_id == source_project_id,
                    LemmaDocStat.doc_id.in_(selected_source_doc_ids),
                )
                .order_by(LemmaDocStat.doc_id.asc(), LemmaDocStat.lemma_id.asc())
            )
            .scalars()
            .all()
        )
        agg: dict[int, dict[str, Any]] = {}
        for row in source_lemma_stats:
            mapped_doc_id = doc_id_map.get(int(row.doc_id))
            mapped_lemma_id = lemma_id_map.get(int(row.lemma_id))
            if mapped_doc_id is None or mapped_lemma_id is None:
                continue
            mapped_sample_sentence = None
            if row.sample_sentence_id is not None:
                mapped_sample_sentence = sentence_id_map.get(int(row.sample_sentence_id))

            session.add(
                LemmaDocStat(
                    project_id=bench_project.project_id,
                    doc_id=mapped_doc_id,
                    lemma_id=mapped_lemma_id,
                    freq_abs=row.freq_abs,
                    sample_sentence_id=mapped_sample_sentence,
                )
            )
            copied_lemma_doc_stats += 1

            stat = agg.setdefault(
                mapped_lemma_id,
                {
                    "freq_abs": 0,
                    "doc_ids": set(),
                    "sample_sentence_id": None,
                },
            )
            stat["freq_abs"] += int(row.freq_abs or 0)
            stat["doc_ids"].add(mapped_doc_id)
            if stat["sample_sentence_id"] is None and mapped_sample_sentence is not None:
                stat["sample_sentence_id"] = mapped_sample_sentence

        for mapped_lemma_id in sorted(agg.keys()):
            stat = agg[mapped_lemma_id]
            session.add(
                LemmaProjectStat(
                    project_id=bench_project.project_id,
                    lemma_id=mapped_lemma_id,
                    freq_abs=int(stat["freq_abs"]),
                    doc_freq=len(stat["doc_ids"]),
                    sample_sentence_id=stat["sample_sentence_id"],
                )
            )

    session.commit()

    bench_doc_ids = [doc_id_map[doc_id] for doc_id in selected_source_doc_ids if doc_id in doc_id_map]
    bench_sentence_ids = (
        session.execute(
            select(DocumentSentence.sentence_id)
            .where(DocumentSentence.doc_id.in_(bench_doc_ids))
            .order_by(DocumentSentence.sentence_id.asc())
        )
        .scalars()
        .all()
    )

    return {
        "source_project_id": int(source_project.project_id),
        "source_project_name": str(source_project.name),
        "bench_project_id": int(bench_project.project_id),
        "bench_project_name": str(bench_project.name),
        "bench_corpus_id": int(bench_corpus.corpus_id),
        "src_lang": str(bench_project.src_lang),
        "tgt_lang": str(bench_project.tgt_lang),
        "selected_source_doc_ids": [int(x) for x in selected_source_doc_ids],
        "bench_doc_ids": [int(x) for x in bench_doc_ids],
        "bench_sentence_ids": [int(x) for x in bench_sentence_ids],
        "copied_counts": {
            "documents": len(doc_id_map),
            "document_texts": len(source_texts),
            "sentences": len(sentence_id_map),
            "lemmas": len(lemma_id_map),
            "lemma_doc_stats": copied_lemma_doc_stats,
        },
    }


def _load_scope_rows(
    session,
    *,
    bench_project_id: int,
    lemma_limit: int,
    term_limit: int,
    sentence_limit: int,
) -> dict[str, list[dict[str, Any]]]:
    from sqlalchemy import select
    from app.infra.sa_models import DocumentSentence, Lemma, SourceCorpus, SourceDocument, TermCluster

    lemmas = (
        session.execute(
            select(Lemma.lemma_id, Lemma.lemma_text, Lemma.norm_text)
            .where(Lemma.project_id == bench_project_id)
            .order_by(Lemma.lemma_id.asc())
            .limit(lemma_limit)
        )
        .all()
    )
    terms = (
        session.execute(
            select(TermCluster.cluster_id, TermCluster.representative_he, TermCluster.norm_text)
            .where(TermCluster.project_id == bench_project_id)
            .order_by(TermCluster.cluster_id.asc())
            .limit(term_limit)
        )
        .all()
    )
    sentences = (
        session.execute(
            select(DocumentSentence.sentence_id, DocumentSentence.text)
            .join(SourceDocument, DocumentSentence.doc_id == SourceDocument.doc_id)
            .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
            .where(SourceCorpus.project_id == bench_project_id)
            .order_by(DocumentSentence.sentence_id.asc())
            .limit(sentence_limit)
        )
        .all()
    )

    return {
        "lemmas": [
            {
                "id": int(row.lemma_id),
                "text": str(row.lemma_text or ""),
                "norm_text": str(row.norm_text or ""),
            }
            for row in lemmas
            if str(row.lemma_text or "").strip()
        ],
        "terms": [
            {
                "id": int(row.cluster_id),
                "text": str(row.representative_he or ""),
                "norm_text": str(row.norm_text or ""),
            }
            for row in terms
            if str(row.representative_he or "").strip()
        ],
        "sentences": [
            {
                "id": int(row.sentence_id),
                "text": str(row.text or ""),
            }
            for row in sentences
            if str(row.text or "").strip()
        ],
    }


def _run_extract_terms(session, *, bench_project_id: int, overwrite: bool) -> dict[str, Any]:
    from sqlalchemy import func, select
    from app.infra.sa_models import Lemma, SourceCorpus, SourceDocument, TermCluster, DocumentSentence
    from app.services.term_extraction_service import TermExtractionService

    started = _utc_now().isoformat()
    t0 = time.perf_counter()
    service = TermExtractionService()
    report = service.extract_terms_for_project(
        session,
        bench_project_id,
        overwrite=overwrite,
    )
    session.commit()

    if not report.success:
        raise RuntimeError(report.error_message or "extract_terms_for_project returned success=False")

    lemma_count = int(
        session.execute(
            select(func.count(Lemma.lemma_id)).where(Lemma.project_id == bench_project_id)
        ).scalar_one()
    )
    term_count = int(
        session.execute(
            select(func.count(TermCluster.cluster_id)).where(TermCluster.project_id == bench_project_id)
        ).scalar_one()
    )
    sentence_count = int(
        session.execute(
            select(func.count(DocumentSentence.sentence_id))
            .select_from(DocumentSentence)
            .join(SourceDocument, DocumentSentence.doc_id == SourceDocument.doc_id)
            .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
            .where(SourceCorpus.project_id == bench_project_id)
        ).scalar_one()
    )

    return {
        "name": "extract_terms",
        "started_at_utc": started,
        "ended_at_utc": _utc_now().isoformat(),
        "duration_sec": round(time.perf_counter() - t0, 3),
        "rows_processed": {
            "lemma": lemma_count,
            "term": term_count,
            "sentence": sentence_count,
        },
        "overwrite": bool(overwrite),
        "errors_count": 0,
        "error_samples": [],
        "details": {
            "ngrams_extracted": int(report.ngrams_extracted),
            "np_chunks_extracted": int(report.np_chunks_extracted),
            "clusters_created": int(report.clusters_created),
        },
    }

def _run_niqqud_bootstrap(
    session,
    *,
    bench_project_id: int,
    src_lang: str,
    overwrite: bool,
    scope_rows: dict[str, list[dict[str, Any]]],
    model_path: str,
    pron_chunk_size: int,
    sentence_chunk_size: int,
    sentence_sub_chunk_size: int,
) -> dict[str, Any]:
    from app.domain.normalization.normalizer import normalize_for_tm
    from app.services.pronunciation_bootstrap_service import (
        PhonikudPronunciationGenerator,
        PronunciationBootstrapService,
    )
    from app.services.sentence_pronunciation_bootstrap_service import SentencePronunciationBootstrapService

    started = _utc_now().isoformat()
    t0 = time.perf_counter()
    generator = PhonikudPronunciationGenerator(model_path=model_path, enabled=True)
    health = generator.health_check()

    lexical_items: list[dict[str, Any]] = []
    for row in scope_rows["lemmas"]:
        text = row["text"]
        norm = row["norm_text"] or normalize_for_tm(src_lang, text, "lemma").norm or ""
        norm = str(norm).strip()
        if not norm:
            continue
        lexical_items.append(
            {
                "src_lang": src_lang,
                "src_norm": norm,
                "raw_src_norm": norm,
                "src_text": text,
                "source_group": "lemmas",
            }
        )

    for row in scope_rows["terms"]:
        text = row["text"]
        norm = row["norm_text"] or normalize_for_tm(src_lang, text, "term_cluster").norm or ""
        norm = str(norm).strip()
        if not norm:
            continue
        lexical_items.append(
            {
                "src_lang": src_lang,
                "src_norm": norm,
                "raw_src_norm": norm,
                "src_text": text,
                "source_group": "terms",
            }
        )

    lexical_service = PronunciationBootstrapService(generator=generator)
    lexical_result = lexical_service.bootstrap(
        session,
        lang=src_lang,
        chunk_size=max(1, int(pron_chunk_size)),
        rebuild_auto=overwrite,
        include_lemmas=True,
        include_terms=True,
        include_user_dictionary=False,
        include_sentences=False,
        selected_items=lexical_items,
    )

    sentence_service = SentencePronunciationBootstrapService(
        chunk_size=max(1, int(sentence_chunk_size)),
        sub_chunk_size=max(1, int(sentence_sub_chunk_size)),
    )
    sentence_ids = [int(row["id"]) for row in scope_rows["sentences"]]
    sentence_mode = "rebuild" if overwrite else "fill_only"
    sentence_result = sentence_service.run(
        session,
        sentence_ids=sentence_ids,
        lang=src_lang,
        mode=sentence_mode,
        phonikud_generator=generator,
        phonikud_version=health.mode,
    )
    session.commit()

    return {
        "name": "niqqud_bootstrap",
        "started_at_utc": started,
        "ended_at_utc": _utc_now().isoformat(),
        "duration_sec": round(time.perf_counter() - t0, 3),
        "rows_processed": {
            "lemma": len(scope_rows["lemmas"]),
            "term": len(scope_rows["terms"]),
            "sentence": len(scope_rows["sentences"]),
        },
        "overwrite": bool(overwrite),
        "errors_count": int(lexical_result.failed + sentence_result.failed),
        "error_samples": [],
        "details": {
            "health": {
                "mode": health.mode,
                "status": health.status,
                "latency_ms": int(health.latency_ms),
                "model_path": health.model_path,
            },
            "lexical": {
                "updated": int(lexical_result.updated),
                "skipped": int(lexical_result.skipped),
                "failed": int(lexical_result.failed),
                "generated_candidates": int(lexical_result.generated_candidates),
                "generator_mode": str(lexical_result.generator_mode),
            },
            "sentence": {
                "inserted": int(sentence_result.inserted),
                "updated": int(sentence_result.updated),
                "skipped_total": int(sentence_result.skipped_total),
                "failed": int(sentence_result.failed),
                "generator_mode": str(sentence_result.generator_mode),
                "elapsed_seconds": float(sentence_result.elapsed_seconds),
            },
        },
    }


def _run_translate_bootstrap(
    session,
    *,
    bench_project_id: int,
    src_lang: str,
    tgt_lang: str,
    overwrite: bool,
    scope_rows: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    from app.services.batch_mt_translate_service import (
        BatchMTTranslateService,
        BatchTranslateItem,
        BatchTranslateOptions,
    )

    started = _utc_now().isoformat()
    t0 = time.perf_counter()
    service = BatchMTTranslateService()
    options = BatchTranslateOptions(
        provider_mode="force:google_cloud_translate",
        write_mode="OVERWRITE" if overwrite else "FILL_EMPTY",
    )

    summaries: dict[str, dict[str, int]] = {}
    error_samples: list[str] = []

    def _execute(items: list[BatchTranslateItem], scope: str) -> None:
        result = service.execute_batch(
            session=session,
            items=items,
            options=options,
        )
        summaries[scope] = {
            "total": int(result.total),
            "succeeded": int(result.succeeded),
            "skipped": int(result.skipped),
            "failed": int(result.failed),
        }
        for row in result.row_results:
            if row.error_message and len(error_samples) < 5:
                error_samples.append(str(row.error_message))

    lemma_items = [
        BatchTranslateItem(
            entity_type="lemma",
            entity_id=str(row["id"]),
            source_text=row["text"],
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            current_translation=None,
            project_id=bench_project_id,
        )
        for row in scope_rows["lemmas"]
    ]
    _execute(lemma_items, "lemma")

    term_items = [
        BatchTranslateItem(
            entity_type="term_cluster",
            entity_id=str(row["id"]),
            source_text=row["text"],
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            current_translation=None,
            project_id=bench_project_id,
        )
        for row in scope_rows["terms"]
    ]
    _execute(term_items, "term")

    sentence_items = [
        BatchTranslateItem(
            entity_type="surface",
            entity_id=str(row["id"]),
            source_text=row["text"],
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            current_translation=None,
            project_id=bench_project_id,
        )
        for row in scope_rows["sentences"]
    ]
    _execute(sentence_items, "sentence")
    session.commit()

    total_failed = sum(v["failed"] for v in summaries.values())
    return {
        "name": "translate_bootstrap",
        "started_at_utc": started,
        "ended_at_utc": _utc_now().isoformat(),
        "duration_sec": round(time.perf_counter() - t0, 3),
        "rows_processed": {
            "lemma": len(scope_rows["lemmas"]),
            "term": len(scope_rows["terms"]),
            "sentence": len(scope_rows["sentences"]),
        },
        "overwrite": bool(overwrite),
        "errors_count": int(total_failed),
        "error_samples": error_samples[:5],
        "details": summaries,
    }

def _run_tts_bootstrap(
    session,
    *,
    src_lang: str,
    overwrite: bool,
    scope_rows: dict[str, list[dict[str, Any]]],
    tts_commit_chunk: int,
) -> dict[str, Any]:
    from app.domain.normalization.normalizer import normalize_for_tm
    from app.services.audio_generation_service import AudioGenerationService

    started = _utc_now().isoformat()
    t0 = time.perf_counter()
    service = AudioGenerationService()
    summaries = {
        "lemma": {"total": 0, "succeeded": 0, "skipped": 0, "failed": 0},
        "term": {"total": 0, "succeeded": 0, "skipped": 0, "failed": 0},
        "sentence": {"total": 0, "succeeded": 0, "skipped": 0, "failed": 0},
    }
    error_samples: list[str] = []
    pending = 0
    commit_chunk = max(1, int(tts_commit_chunk))

    def _handle(scope: str, row_id: int, text: str, norm_hint: str, kind: str) -> None:
        nonlocal pending
        summaries[scope]["total"] += 1
        norm_value = (norm_hint or "").strip() or (normalize_for_tm(src_lang, text, kind).norm or "").strip()
        if not norm_value:
            summaries[scope]["failed"] += 1
            if len(error_samples) < 5:
                error_samples.append(f"{scope}:{row_id}: empty norm")
            return
        result = service.generate_one(
            session=session,
            src_text=text,
            src_lang=src_lang,
            source_norm=norm_value,
            provider_mode="force:google_cloud_tts",
            force_regenerate=overwrite,
            trace_id=f"bench_tts:{scope}:{row_id}",
        )
        pending += 1
        if pending >= commit_chunk:
            session.commit()
            pending = 0

        if result.get("ok"):
            if result.get("status") == "skipped":
                summaries[scope]["skipped"] += 1
            else:
                summaries[scope]["succeeded"] += 1
            return

        summaries[scope]["failed"] += 1
        if len(error_samples) < 5:
            msg = str(result.get("error") or "unknown audio generation error")
            error_samples.append(f"{scope}:{row_id}: {msg}")

    for row in scope_rows["lemmas"]:
        _handle("lemma", int(row["id"]), str(row["text"]), str(row["norm_text"]), "lemma")
    for row in scope_rows["terms"]:
        _handle("term", int(row["id"]), str(row["text"]), str(row["norm_text"]), "term_cluster")
    for row in scope_rows["sentences"]:
        _handle("sentence", int(row["id"]), str(row["text"]), "", "surface")

    if pending:
        session.commit()

    total_failed = sum(scope["failed"] for scope in summaries.values())
    return {
        "name": "tts_bootstrap",
        "started_at_utc": started,
        "ended_at_utc": _utc_now().isoformat(),
        "duration_sec": round(time.perf_counter() - t0, 3),
        "rows_processed": {
            "lemma": len(scope_rows["lemmas"]),
            "term": len(scope_rows["terms"]),
            "sentence": len(scope_rows["sentences"]),
        },
        "overwrite": bool(overwrite),
        "errors_count": int(total_failed),
        "error_samples": error_samples[:5],
        "details": summaries,
    }


def _run_stage(name: str, fn) -> dict[str, Any]:
    started = _utc_now().isoformat()
    t0 = time.perf_counter()
    try:
        result = fn()
        result["status"] = "ok"
        if "started_at_utc" not in result:
            result["started_at_utc"] = started
        if "ended_at_utc" not in result:
            result["ended_at_utc"] = _utc_now().isoformat()
        if "duration_sec" not in result:
            result["duration_sec"] = round(time.perf_counter() - t0, 3)
        return result
    except Exception as exc:
        return {
            "name": name,
            "status": "error",
            "started_at_utc": started,
            "ended_at_utc": _utc_now().isoformat(),
            "duration_sec": round(time.perf_counter() - t0, 3),
            "rows_processed": {"lemma": 0, "term": 0, "sentence": 0},
            "errors_count": 1,
            "error_samples": [str(exc)],
            "details": {"traceback": traceback.format_exc(limit=12)},
        }


def _write_markdown_report(report: dict[str, Any], md_path: Path) -> None:
    db_info = report.get("db") or {}
    bench_info = report.get("bench") or {}
    timings = report.get("timings") or {}
    cleanup_details = ((report.get("stages") or [{}])[0].get("details") or {}) if report.get("scenario") == "cleanup_sandbox" else {}
    reset_details = ((report.get("stages") or [{}])[0].get("details") or {}) if report.get("scenario") == "reset_sandbox" else {}
    post_run_maintenance = db_info.get("post_run_maintenance") or {}
    cycle_actions = ((report.get("maintenance_cycle") or {}).get("actions") or [])
    stage_total = round(
        sum(float(stage.get("duration_sec", 0.0) or 0.0) for stage in report.get("stages", [])),
        3,
    )
    lines: list[str] = []
    lines.append("# Pipeline Benchmark Report (PATCH-05)")
    lines.append("")
    lines.append(f"- Timestamp UTC: `{report['timestamp_utc']}`")
    lines.append(f"- Scenario: `{report['scenario']}`")
    lines.append(f"- Overall status: `{report['overall_status']}`")
    lines.append(f"- Base sandbox DB: `{db_info.get('base_sandbox_db', 'n/a')}`")
    lines.append(f"- Source DB: `{db_info.get('source_db') or 'n/a'}`")
    lines.append(f"- Working DB (temp): `{db_info.get('working_db', 'n/a')}`")
    if timings.get("base_copy_reused"):
        lines.append("- Base sandbox copy: `reused existing file`")
    if timings.get("working_db_reused"):
        lines.append("- Working DB copy: `reused sandbox file in place`")
    lines.append("")
    if report["scenario"] not in {"cleanup_sandbox", "reset_sandbox"}:
        lines.append("## Bench Slice")
        lines.append("")
        lines.append(
            f"- Source project: `{bench_info.get('source_project_id', 'n/a')}` "
            f"(`{bench_info.get('source_project_name', 'n/a')}`)"
        )
        lines.append(
            f"- Bench project: `{bench_info.get('bench_project_id', 'n/a')}` "
            f"(`{bench_info.get('bench_project_name', 'n/a')}`)"
        )
        if report["config"].get("tier"):
            lines.append(f"- Tier: `{report['config']['tier']}`")
        if report["config"].get("recommended_wall_budget_sec") is not None:
            lines.append(
                f"- Recommended wall budget: `{int(report['config']['recommended_wall_budget_sec'])} s`"
            )
        if report["config"].get("pre_reset_sandbox"):
            lines.append("- Pre-reset sandbox: `enabled`")
        if report["config"].get("post_cleanup_bench"):
            lines.append("- Post-cleanup bench: `enabled`")
        lines.append(f"- Doc limit: `{report['config']['doc_limit']}`")
        lines.append(f"- Selected docs: `{len(bench_info.get('selected_source_doc_ids', []))}`")
        lines.append("")
    if report["scenario"] == "cleanup_sandbox":
        lines.append("## Cleanup Summary")
        lines.append("")
        lines.append(f"- Deleted projects: `{int(cleanup_details.get('deleted_count', 0))}`")
        lines.append(f"- Cleanup prefix: `{cleanup_details.get('cleanup_prefix', '')}`")
        if cleanup_details.get("cleanup_project_name"):
            lines.append(f"- Cleanup project name: `{cleanup_details.get('cleanup_project_name')}`")
        lines.append("")
    if report["scenario"] == "reset_sandbox":
        lines.append("## Reset Summary")
        lines.append("")
        lines.append(f"- Source DB: `{reset_details.get('source_db', 'n/a')}`")
        lines.append(f"- Target DB: `{reset_details.get('target_db', 'n/a')}`")
        lines.append(f"- Target size bytes: `{int(reset_details.get('size_bytes', 0))}`")
        lines.append("")
    lines.append("## Timing Breakdown")
    lines.append("")
    lines.append(f"- Base sandbox copy: `{float(timings.get('base_copy_sec', 0.0)):.3f} s`")
    lines.append(f"- Working DB copy: `{float(timings.get('working_copy_sec', 0.0)):.3f} s`")
    lines.append(f"- DB initialize: `{float(timings.get('db_initialize_sec', 0.0)):.3f} s`")
    lines.append(f"- Bench slice clone: `{float(timings.get('slice_clone_sec', 0.0)):.3f} s`")
    lines.append(f"- Pre-stage overhead total: `{float(timings.get('pre_stage_overhead_sec', 0.0)):.3f} s`")
    if timings.get("post_run_maintenance_sec") is not None:
        lines.append(
            f"- Post-run maintenance: `{float(timings.get('post_run_maintenance_sec', 0.0)):.3f} s`"
        )
    if timings.get("post_cleanup_bench_sec") is not None:
        lines.append(
            f"- Post-cleanup bench: `{float(timings.get('post_cleanup_bench_sec', 0.0)):.3f} s`"
        )
    lines.append(f"- Stage wall total: `{stage_total:.3f} s`")
    lines.append(f"- Overall wall total: `{float(timings.get('overall_wall_sec', 0.0)):.3f} s`")
    lines.append("")
    if cycle_actions:
        lines.append("## Maintenance Cycle")
        lines.append("")
        for action in cycle_actions:
            lines.append(
                f"- {action.get('name')}: status=`{action.get('status')}` "
                f"duration=`{float(action.get('duration_sec', 0.0)):.3f} s` "
                f"details=`{action.get('details', {})}`"
            )
        lines.append("")
    if post_run_maintenance:
        lines.append("## SQLite Maintenance")
        lines.append("")
        for db_path, details in sorted(post_run_maintenance.items()):
            lines.append(f"- DB: `{db_path}`")
            lines.append(
                f"  checkpoint={details.get('checkpoint_result')} "
                f"before={details.get('before', {})} after={details.get('after', {})}"
            )
        lines.append("")
    lines.append("## Stage Summary")
    lines.append("")
    lines.append("| Stage | Status | Duration (s) | Lemma | Term | Sentence | Errors |")
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    for stage in report["stages"]:
        rows = stage.get("rows_processed", {})
        lines.append(
            f"| {stage.get('name')} | {stage.get('status')} | {float(stage.get('duration_sec', 0.0)):.3f} | "
            f"{int(rows.get('lemma', 0))} | {int(rows.get('term', 0))} | {int(rows.get('sentence', 0))} | "
            f"{int(stage.get('errors_count', 0))} |"
        )
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- Log: `{report['artifacts']['latest_log']}`")
    lines.append(f"- JSON: `{report['artifacts']['metrics_json']}`")
    lines.append(f"- Markdown: `{report['artifacts']['report_md']}`")
    lines.append("")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark real pipeline stages on sandbox-only DB copies.",
    )
    subparsers = parser.add_subparsers(dest="scenario", required=True)

    def _add_common_arguments(cmd_parser: argparse.ArgumentParser) -> None:
        cmd_parser.add_argument("--db-path", required=True, default=DEFAULT_SANDBOX_DB)
        cmd_parser.add_argument("--copy-target", action="store_true")
        cmd_parser.add_argument("--reuse-base-copy", action="store_true")
        cmd_parser.add_argument("--reuse-working-db", action="store_true")
        cmd_parser.add_argument("--pre-reset-sandbox", action="store_true")
        cmd_parser.add_argument("--post-cleanup-bench", action="store_true")
        cmd_parser.add_argument("--tier", choices=tuple(BENCH_TIER_PRESETS.keys()))
        cmd_parser.add_argument("--source-db", required=True, default=DEFAULT_SOURCE_DB)
        cmd_parser.add_argument("--source-project-id", type=int, default=1)
        cmd_parser.add_argument("--bench-project-name", default=DEFAULT_PROJECT_NAME)
        cmd_parser.add_argument("--doc-limit", type=int, default=6000)
        cmd_parser.add_argument("--overwrite", type=int, choices=(0, 1), default=1)

        cmd_parser.add_argument("--lemma-limit", type=int, default=1000)
        cmd_parser.add_argument("--term-limit", type=int, default=1000)
        cmd_parser.add_argument("--sentence-limit", type=int, default=1000)

        cmd_parser.add_argument("--phonikud-model-path", default=DEFAULT_PHONIKUD_MODEL_PATH)
        cmd_parser.add_argument("--gct-key-path", default=DEFAULT_GCT_KEY_PATH)
        cmd_parser.add_argument("--gctts-key-path", default=DEFAULT_GCTTS_KEY_PATH)

        cmd_parser.add_argument("--pron-chunk-size", type=int, default=200)
        cmd_parser.add_argument("--sentence-chunk-size", type=int, default=200)
        cmd_parser.add_argument("--sentence-sub-chunk-size", type=int, default=50)
        cmd_parser.add_argument("--tts-commit-chunk", type=int, default=25)

        cmd_parser.add_argument("--output-dir", default="build/logs")
        cmd_parser.add_argument("--temp-root", default=DEFAULT_TEMP_ROOT)

    def _add_cleanup_arguments(cmd_parser: argparse.ArgumentParser) -> None:
        cmd_parser.add_argument("--db-path", required=True)
        cmd_parser.add_argument("--copy-target", action="store_true")
        cmd_parser.add_argument("--cleanup-prefix", default=DEFAULT_BENCH_PREFIX)
        cmd_parser.add_argument("--cleanup-project-name", default="")
        cmd_parser.add_argument("--output-dir", default="build/logs")
        cmd_parser.add_argument("--temp-root", default=DEFAULT_TEMP_ROOT)

    def _add_reset_arguments(cmd_parser: argparse.ArgumentParser) -> None:
        cmd_parser.add_argument("--db-path", required=True)
        cmd_parser.add_argument("--copy-target", action="store_true")
        cmd_parser.add_argument("--source-db", required=True, default=DEFAULT_SOURCE_DB)
        cmd_parser.add_argument("--output-dir", default="build/logs")
        cmd_parser.add_argument("--temp-root", default=DEFAULT_TEMP_ROOT)

    for name in (
        "extract_terms",
        "niqqud_bootstrap",
        "translate_bootstrap",
        "tts_bootstrap",
        "all",
    ):
        child = subparsers.add_parser(name, help=f"Run scenario: {name}")
        _add_common_arguments(child)

    cleanup = subparsers.add_parser(
        "cleanup_sandbox",
        help="Delete benchmark projects from a sandbox DB by prefix or exact name.",
    )
    _add_cleanup_arguments(cleanup)
    reset = subparsers.add_parser(
        "reset_sandbox",
        help="Replace sandbox DB with a fresh copy of source DB.",
    )
    _add_reset_arguments(reset)
    return parser


def build_parser() -> argparse.ArgumentParser:
    """Public parser factory for tests."""
    return _build_parser()


def run(argv: list[str] | None = None) -> int:
    raw_argv = list(argv or [])
    args = _build_parser().parse_args(argv)
    tier = resolve_tier_preset(args, raw_argv)
    paths = build_artifact_file_paths(Path(args.output_dir))
    _setup_logging(paths["latest_log"])

    report: dict[str, Any] = {
        "timestamp_utc": _utc_now().isoformat(),
        "scenario": args.scenario,
        "overall_status": "error",
        "build_meta": _load_build_meta(),
        "config": {
            "doc_limit": int(getattr(args, "doc_limit", 0) or 0),
            "overwrite": int(getattr(args, "overwrite", 0) or 0),
            "lemma_limit": int(getattr(args, "lemma_limit", 0) or 0),
            "term_limit": int(getattr(args, "term_limit", 0) or 0),
            "sentence_limit": int(getattr(args, "sentence_limit", 0) or 0),
            "copy_target": bool(args.copy_target),
            "reuse_base_copy": bool(getattr(args, "reuse_base_copy", False)),
            "reuse_working_db": bool(getattr(args, "reuse_working_db", False)),
            "pre_reset_sandbox": bool(getattr(args, "pre_reset_sandbox", False)),
            "post_cleanup_bench": bool(getattr(args, "post_cleanup_bench", False)),
            "tier": tier["name"],
            "recommended_wall_budget_sec": tier["recommended_wall_budget_sec"],
            "bench_project_name": str(getattr(args, "bench_project_name", "")),
            "cleanup_prefix": str(getattr(args, "cleanup_prefix", "")),
            "cleanup_project_name": str(getattr(args, "cleanup_project_name", "")),
            "temp_root": str(getattr(args, "temp_root", "")),
        },
        "db": {},
        "bench": {},
        "stages": [],
        "timings": {},
        "artifacts": {
            "latest_log": str(paths["latest_log"].resolve()),
            "metrics_json": str(paths["metrics_json"].resolve()),
            "report_md": str(paths["report_md"].resolve()),
        },
    }
    overall_t0 = time.perf_counter()

    try:
        _validate_runtime_contract(args)

        if args.scenario == "cleanup_sandbox":
            base_db = Path(args.db_path).expanduser().resolve()
            report["timings"]["base_copy_sec"] = 0.0
            report["timings"]["working_copy_sec"] = 0.0
            report["timings"]["db_initialize_sec"] = 0.0
            report["timings"]["slice_clone_sec"] = 0.0
            report["timings"]["pre_stage_overhead_sec"] = 0.0
            report["timings"]["base_copy_reused"] = True
            report["timings"]["working_db_reused"] = True
            report["db"] = {
                "source_db": None,
                "base_sandbox_db": str(base_db),
                "working_db": str(base_db),
                "safety": {
                    "copy_target": bool(args.copy_target),
                    "forbidden_m_path_enforced": True,
                    "cleanup_direct": True,
                },
            }
            _reset_db_service()
            from app.services.db_service import DBService

            t0 = time.perf_counter()
            DBService.initialize(base_db)
            report["timings"]["db_initialize_sec"] = round(time.perf_counter() - t0, 3)
            report["timings"]["pre_stage_overhead_sec"] = float(report["timings"]["db_initialize_sec"])
            db_service = DBService.get_instance()
            with db_service.get_session() as session:
                stage_result = _run_stage(
                    "cleanup_sandbox",
                    lambda: _run_cleanup_sandbox(
                        session,
                        cleanup_project_name=str(getattr(args, "cleanup_project_name", "") or "").strip() or None,
                        cleanup_prefix=str(getattr(args, "cleanup_prefix", DEFAULT_BENCH_PREFIX) or "").strip(),
                    ),
                )
            report["stages"].append(stage_result)
            report["overall_status"] = "pass" if stage_result.get("status") == "ok" else "fail"
            return_code = 0 if report["overall_status"] == "pass" else 1
            return return_code

        if args.scenario == "reset_sandbox":
            source_db = Path(args.source_db).expanduser().resolve()
            base_db = Path(args.db_path).expanduser().resolve()
            report["db"] = {
                "source_db": str(source_db),
                "base_sandbox_db": str(base_db),
                "working_db": str(base_db),
                "safety": {
                    "copy_target": bool(args.copy_target),
                    "forbidden_m_path_enforced": True,
                    "reset_direct": True,
                },
            }
            t0 = time.perf_counter()
            _prepare_base_sandbox(base_db, source_db, reuse_existing=False)
            reset_duration = round(time.perf_counter() - t0, 3)
            report["timings"]["base_copy_sec"] = float(reset_duration)
            report["timings"]["working_copy_sec"] = 0.0
            report["timings"]["db_initialize_sec"] = 0.0
            report["timings"]["slice_clone_sec"] = 0.0
            report["timings"]["pre_stage_overhead_sec"] = float(reset_duration)
            report["timings"]["base_copy_reused"] = False
            report["timings"]["working_db_reused"] = True
            stage_result = _run_stage(
                "reset_sandbox",
                lambda: _run_reset_sandbox(
                    base_db=base_db,
                    source_db=source_db,
                    duration_sec=reset_duration,
                ),
            )
            report["stages"].append(stage_result)
            report["overall_status"] = "pass" if stage_result.get("status") == "ok" else "fail"
            return_code = 0 if report["overall_status"] == "pass" else 1
            return return_code

        source_db = Path(args.source_db).expanduser().resolve()
        base_db = Path(args.db_path).expanduser().resolve()
        temp_root = Path(args.temp_root).expanduser().resolve()
        _cleanup_temp_root(temp_root)
        t0 = time.perf_counter()
        reuse_base_copy = bool(args.reuse_base_copy)
        if bool(getattr(args, "pre_reset_sandbox", False)):
            reuse_base_copy = False
        base_copy_performed = _prepare_base_sandbox(
            base_db,
            source_db,
            reuse_existing=reuse_base_copy,
        )
        base_copy_duration = round(time.perf_counter() - t0, 3) if base_copy_performed else 0.0
        report["timings"]["base_copy_sec"] = base_copy_duration
        report["timings"]["base_copy_reused"] = not base_copy_performed
        report["timings"]["working_db_reused"] = bool(args.reuse_working_db)
        if bool(getattr(args, "pre_reset_sandbox", False)):
            _record_cycle_action(
                report,
                name="pre_reset_sandbox",
                status="ok" if base_copy_performed else "skipped",
                duration_sec=base_copy_duration,
                details={
                    "base_db": str(base_db),
                    "source_db": str(source_db),
                    "base_copy_performed": bool(base_copy_performed),
                },
            )
        working_db_ctx = (
            nullcontext((base_db, 0.0))
            if args.reuse_working_db
            else _working_db_copy(base_db, temp_root)
        )

        with working_db_ctx as (working_db, working_copy_sec):
            report["timings"]["working_copy_sec"] = float(working_copy_sec)
            report["db"] = {
                "source_db": str(source_db),
                "base_sandbox_db": str(base_db),
                "working_db": str(working_db),
                "safety": {
                    "copy_target": bool(args.copy_target),
                    "forbidden_m_path_enforced": True,
                    "base_copy_reused": bool(report["timings"]["base_copy_reused"]),
                    "working_db_reused": bool(report["timings"]["working_db_reused"]),
                },
            }

            _reset_db_service()
            from app.services.db_service import DBService

            t0 = time.perf_counter()
            DBService.initialize(working_db)
            report["timings"]["db_initialize_sec"] = round(time.perf_counter() - t0, 3)
            db_service = DBService.get_instance()

            with db_service.get_session() as session:
                t0 = time.perf_counter()
                bench = _clone_slice_into_bench_project(
                    session,
                    source_project_id=int(args.source_project_id),
                    bench_project_name=str(args.bench_project_name),
                    doc_limit=int(args.doc_limit),
                )
                report["timings"]["slice_clone_sec"] = round(time.perf_counter() - t0, 3)
                report["bench"] = bench

            planned_stages: list[str]
            if args.scenario == "all":
                planned_stages = [
                    "extract_terms",
                    "niqqud_bootstrap",
                    "translate_bootstrap",
                    "tts_bootstrap",
                ]
            else:
                planned_stages = [args.scenario]

            overwrite_flag = bool(int(args.overwrite))
            for stage_name in planned_stages:
                with db_service.get_session() as session:
                    scope_rows = _load_scope_rows(
                        session,
                        bench_project_id=int(report["bench"]["bench_project_id"]),
                        lemma_limit=int(args.lemma_limit),
                        term_limit=int(args.term_limit),
                        sentence_limit=int(args.sentence_limit),
                    )

                    if stage_name == "extract_terms":
                        stage_result = _run_stage(
                            stage_name,
                            lambda: _run_extract_terms(
                                session,
                                bench_project_id=int(report["bench"]["bench_project_id"]),
                                overwrite=overwrite_flag,
                            ),
                        )
                    elif stage_name == "niqqud_bootstrap":
                        model_path = Path(args.phonikud_model_path).expanduser().resolve()
                        if not model_path.exists():
                            raise FileNotFoundError(
                                f"Niqqud model path not found: {model_path}. "
                                "Set --phonikud-model-path to ONNX file."
                            )
                        stage_result = _run_stage(
                            stage_name,
                            lambda: _run_niqqud_bootstrap(
                                session,
                                bench_project_id=int(report["bench"]["bench_project_id"]),
                                src_lang=str(report["bench"]["src_lang"]),
                                overwrite=overwrite_flag,
                                scope_rows=scope_rows,
                                model_path=str(model_path),
                                pron_chunk_size=int(args.pron_chunk_size),
                                sentence_chunk_size=int(args.sentence_chunk_size),
                                sentence_sub_chunk_size=int(args.sentence_sub_chunk_size),
                            ),
                        )
                    elif stage_name == "translate_bootstrap":
                        key_path = _resolve_json_path(args.gct_key_path, "Google Cloud Translate key")
                        _configure_google_cloud_translate(key_path)
                        stage_result = _run_stage(
                            stage_name,
                            lambda: _run_translate_bootstrap(
                                session,
                                bench_project_id=int(report["bench"]["bench_project_id"]),
                                src_lang=str(report["bench"]["src_lang"]),
                                tgt_lang=str(report["bench"]["tgt_lang"]),
                                overwrite=overwrite_flag,
                                scope_rows=scope_rows,
                            ),
                        )
                    elif stage_name == "tts_bootstrap":
                        key_path = _resolve_json_path(args.gctts_key_path, "Google Cloud TTS key")
                        _configure_google_cloud_tts(key_path)
                        stage_result = _run_stage(
                            stage_name,
                            lambda: _run_tts_bootstrap(
                                session,
                                src_lang=str(report["bench"]["src_lang"]),
                                overwrite=overwrite_flag,
                                scope_rows=scope_rows,
                                tts_commit_chunk=int(args.tts_commit_chunk),
                            ),
                        )
                    else:
                        raise ValueError(f"Unsupported stage: {stage_name}")

                    report["stages"].append(stage_result)
                    if stage_result.get("status") != "ok":
                        break

            report["overall_status"] = (
                "pass"
                if report["stages"] and all(stage.get("status") == "ok" for stage in report["stages"])
                else "fail"
            )
            if (
                report["overall_status"] == "pass"
                and bool(getattr(args, "post_cleanup_bench", False))
                and report.get("bench", {}).get("bench_project_name")
            ):
                t_cleanup = time.perf_counter()
                with db_service.get_session() as session:
                    cleanup_result = _run_cleanup_sandbox(
                        session,
                        cleanup_project_name=str(report["bench"]["bench_project_name"]),
                        cleanup_prefix=DEFAULT_BENCH_PREFIX,
                    )
                cleanup_duration = round(time.perf_counter() - t_cleanup, 3)
                report["timings"]["post_cleanup_bench_sec"] = cleanup_duration
                _record_cycle_action(
                    report,
                    name="post_cleanup_bench",
                    status="ok",
                    duration_sec=cleanup_duration,
                    details=cleanup_result.get("details", {}),
                )
            report["timings"]["pre_stage_overhead_sec"] = round(
                float(report["timings"].get("base_copy_sec", 0.0))
                + float(report["timings"].get("working_copy_sec", 0.0))
                + float(report["timings"].get("db_initialize_sec", 0.0))
                + float(report["timings"].get("slice_clone_sec", 0.0)),
                3,
            )

    except Exception as exc:
        report["overall_status"] = "fail"
        report.setdefault("errors", [])
        report["errors"].append(
            {
                "message": str(exc),
                "traceback": traceback.format_exc(limit=12),
            }
        )
        LOG.exception("Pipeline benchmark failed")
    finally:
        report["timings"]["overall_wall_sec"] = round(time.perf_counter() - overall_t0, 3)
        try:
            _reset_db_service()
        except Exception:
            pass
        maintenance_started = time.perf_counter()
        maintenance_results: dict[str, Any] = {}
        working_db_raw = (report.get("db") or {}).get("working_db")
        base_db_raw = (report.get("db") or {}).get("base_sandbox_db")
        should_maintain = (
            report.get("scenario") in {"cleanup_sandbox", "reset_sandbox"}
            or bool((report.get("timings") or {}).get("working_db_reused"))
        )
        if should_maintain:
            seen_paths: set[str] = set()
            for raw_path in (working_db_raw, base_db_raw):
                if not raw_path or raw_path in seen_paths or raw_path == "n/a":
                    continue
                seen_paths.add(raw_path)
                db_path = Path(str(raw_path)).expanduser().resolve()
                try:
                    maintenance_results[str(db_path)] = _checkpoint_sqlite_wal(db_path)
                except Exception as exc:
                    maintenance_results[str(db_path)] = {
                        "db_path": str(db_path),
                        "before": _collect_sidecar_sizes(db_path),
                        "after": _collect_sidecar_sizes(db_path),
                        "checkpoint_result": None,
                        "error": str(exc),
                    }
        report["timings"]["post_run_maintenance_sec"] = round(
            time.perf_counter() - maintenance_started,
            3,
        )
        if maintenance_results:
            report.setdefault("db", {})
            report["db"]["post_run_maintenance"] = maintenance_results
        paths["metrics_json"].write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _write_markdown_report(report, paths["report_md"])
        LOG.info("Artifacts:")
        LOG.info("  log: %s", paths["latest_log"])
        LOG.info("  json: %s", paths["metrics_json"])
        LOG.info("  md: %s", paths["report_md"])

    return 0 if report["overall_status"] == "pass" else 1


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
