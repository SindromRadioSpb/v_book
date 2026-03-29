"""Release-grade smoke validation for the managed Windows Stanza runtime."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from sqlalchemy import func, select

from app.infra.nlp_engines.stanza_engine import StanzaEngine, create_stanza_engine
from app.infra.sa_models import ProcessorRun, SourceDocument
from app.services.db_service import DBService
from app.services.nlp_runtime.managed_runtime import ManagedStanzaRuntime
from app.services.process_service import ProcessService


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


@dataclass(frozen=True)
class _ProjectDocContext:
    source_project_id: int
    source_doc_id: int
    project_name: str
    corpus_name: str
    file_name: str
    sha256: str


def _reset_db_service() -> None:
    DBService.shutdown()
    DBService._instance = None
    DBService._db_manager = None
    DBService._ref_managers = {}


def _init_empty_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        for migration_file in sorted(Path("app/infra/migrations").glob("*.sql")):
            conn.executescript(migration_file.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def _load_project_doc_context(source_db: Path, doc_id: int) -> _ProjectDocContext:
    _reset_db_service()
    DBService.initialize(source_db)
    db = DBService.get_instance()
    try:
        with db.get_session() as session:
            doc = session.get(SourceDocument, int(doc_id))
            if doc is None:
                raise RuntimeError(f"Document not found in source DB: {doc_id}")
            corpus = doc.corpus
            if corpus is None:
                raise RuntimeError(f"Document {doc_id} is missing corpus linkage")
            project = corpus.project
            if project is None:
                raise RuntimeError(f"Document {doc_id} is missing project linkage")
            return _ProjectDocContext(
                source_project_id=int(project.project_id),
                source_doc_id=int(doc.doc_id),
                project_name=str(project.name),
                corpus_name=str(corpus.name),
                file_name=str(doc.file_name),
                sha256=str(doc.sha256),
            )
    finally:
        _reset_db_service()


def _fetch_single_row(conn: sqlite3.Connection, table: str, key_column: str, key_value: int) -> dict[str, object]:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        f"SELECT * FROM {table} WHERE {key_column} = ?",
        (int(key_value),),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Missing required row in source DB: {table}.{key_column}={key_value}")
    return dict(row)


def _insert_row(conn: sqlite3.Connection, table: str, row: dict[str, object]) -> None:
    columns = list(row.keys())
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        tuple(row[column] for column in columns),
    )


def _materialize_project_smoke_db(*, source_db: Path, target_db: Path, doc_id: int) -> _ProjectDocContext:
    context = _load_project_doc_context(source_db, int(doc_id))
    source_conn = sqlite3.connect(str(source_db))
    try:
        doc_row = _fetch_single_row(source_conn, "source_document", "doc_id", context.source_doc_id)
        corpus_row = _fetch_single_row(source_conn, "source_corpus", "corpus_id", int(doc_row["corpus_id"]))
        project_row = _fetch_single_row(source_conn, "dict_project", "project_id", int(corpus_row["project_id"]))
        library_row = _fetch_single_row(source_conn, "library", "library_id", int(project_row["library_id"]))
        text_row = source_conn.execute(
            "SELECT * FROM document_text WHERE doc_id = ?",
            (int(context.source_doc_id),),
        ).fetchone()
        if text_row is None:
            raise RuntimeError(f"Document text not found in source DB: {context.source_doc_id}")
        text_payload = dict(text_row)
    finally:
        source_conn.close()

    if project_row.get("general_corpus_id") not in (None, project_row["project_id"]):
        project_row["general_corpus_id"] = None

    target_db.unlink(missing_ok=True)
    _init_empty_db(target_db)
    target_conn = sqlite3.connect(str(target_db))
    try:
        target_conn.execute("PRAGMA foreign_keys = OFF")
        _insert_row(target_conn, "library", library_row)
        _insert_row(target_conn, "dict_project", project_row)
        _insert_row(target_conn, "source_corpus", corpus_row)
        _insert_row(target_conn, "source_document", doc_row)
        _insert_row(target_conn, "document_text", text_payload)
        target_conn.commit()
        target_conn.execute("PRAGMA foreign_keys = ON")
        fk_violations = target_conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_violations:
            raise RuntimeError(f"Smoke DB foreign key violations: {fk_violations[:5]}")
    finally:
        target_conn.close()

    return context


def _resolve_imported_doc_id(target_db: Path, context: _ProjectDocContext) -> tuple[int, int]:
    _reset_db_service()
    DBService.initialize(target_db)
    db = DBService.get_instance()
    try:
        with db.get_session() as session:
            doc = (
                session.query(SourceDocument)
                .join(SourceDocument.corpus)
                .filter(
                    SourceDocument.sha256 == context.sha256,
                    SourceDocument.file_name == context.file_name,
                )
                .order_by(SourceDocument.doc_id)
                .first()
            )
            if doc is None or doc.corpus is None:
                raise RuntimeError(
                    "Imported smoke DB does not contain the requested document after project-scoped import"
                )
            return int(doc.doc_id), int(doc.corpus.project_id)
    finally:
        _reset_db_service()


def _load_managed_runtime_summary() -> dict[str, object]:
    manifest = ManagedStanzaRuntime().load_manifest() or {}
    return {
        "source_kind": str(manifest.get("model_source_kind") or "") or None,
        "source_path": str(manifest.get("model_source_path") or "") or None,
        "bundled_payload_root": str(manifest.get("bundled_payload_root") or "") or None,
        "payload_manifest_path": str(manifest.get("payload_manifest_path") or "") or None,
        "ownership": str(manifest.get("ownership") or "") or None,
    }


def _run_engine_smoke(*, sample_text: str, force_hostile: bool) -> dict[str, object]:
    app = QApplication.instance() or QApplication([])
    _ = app
    summary: dict[str, object] = {
        "sample_text": sample_text,
        "forced_hostile_inprocess": bool(force_hostile),
        "direct_inprocess_failure": None,
        "managed_engine_name": None,
        "managed_engine_version": None,
        "sentence_count": 0,
        "token_count": 0,
    }

    if force_hostile:
        os.environ["HDLE_FORCE_STANZA_INPROCESS_FAILURE"] = "1"
        try:
            try:
                StanzaEngine(use_gpu=False)
            except Exception as exc:
                summary["direct_inprocess_failure"] = str(exc)
        finally:
            os.environ.pop("HDLE_FORCE_STANZA_INPROCESS_FAILURE", None)

    engine = create_stanza_engine(use_gpu=False)
    try:
        sentences = engine.process(sample_text)
        summary["managed_engine_name"] = engine.get_name()
        summary["managed_engine_version"] = engine.get_version()
        summary["sentence_count"] = len(sentences)
        summary["token_count"] = sum(len(sentence.tokens) for sentence in sentences)
    finally:
        close = getattr(engine, "close", None)
        if callable(close):
            close()

    summary.update(_load_managed_runtime_summary())
    return summary


def _run_db_smoke(*, source_db: Path, copy_db_to: Path, doc_id: int) -> dict[str, object]:
    context = _materialize_project_smoke_db(
        source_db=source_db,
        target_db=copy_db_to,
        doc_id=int(doc_id),
    )
    imported_doc_id, imported_project_id = _resolve_imported_doc_id(copy_db_to, context)

    _reset_db_service()
    DBService.initialize(copy_db_to)
    db = DBService.get_instance()
    service = ProcessService()

    try:
        with db.get_session() as session:
            doc = session.get(SourceDocument, int(imported_doc_id))
            if doc is None:
                raise RuntimeError(f"Document not found in project-scoped smoke DB: {imported_doc_id}")

            before_run_id = session.execute(select(func.max(ProcessorRun.run_id))).scalar_one()
            before_run_id = int(before_run_id or 0)

            ok = service.reprocess_document(
                session,
                int(imported_doc_id),
                use_gpu=False,
                use_mock=False,
                configured_engine_id="stanza",
                allow_mock_fallback=False,
                track_run=True,
            )
            latest_run = session.execute(
                select(ProcessorRun)
                .where(ProcessorRun.run_id > before_run_id)
                .order_by(ProcessorRun.run_id.desc())
                .limit(1)
            ).scalar_one_or_none()
            session.refresh(doc)

            report = {
                "db_copy": str(copy_db_to),
                "db_copy_strategy": "document_scoped_clone",
                "source_project_id": int(context.source_project_id),
                "source_doc_id": int(context.source_doc_id),
                "project_id": int(imported_project_id),
                "doc_id": int(imported_doc_id),
                "ok": bool(ok),
                "document_status": str(doc.status),
                "run_engine": str(latest_run.engine) if latest_run is not None else None,
                "run_status": str(latest_run.status) if latest_run is not None else None,
                "runtime_effective": _extract_runtime_effective(latest_run),
                "created_run_id": int(latest_run.run_id) if latest_run is not None else None,
            }
            report.update(_load_managed_runtime_summary())
            return report
    finally:
        _reset_db_service()


def _extract_runtime_effective(run: ProcessorRun | None) -> str | None:
    if run is None:
        return None
    value = getattr(run, "effective_engine_id", None)
    if value:
        return str(value)
    note_text = getattr(run, "note", None)
    if not note_text:
        return None
    try:
        payload = json.loads(note_text)
    except Exception:
        return None
    runtime = payload.get("runtime")
    if isinstance(runtime, dict):
        value = runtime.get("effective_engine_id")
        return str(value) if value else None
    value = payload.get("effective_engine_id")
    return str(value) if value else None


def _assert_expected_source(
    summary: dict[str, object],
    *,
    label: str,
    require_source_kind: str | None,
    require_bundled_source: bool,
) -> None:
    source_kind = str(summary.get("source_kind") or "") or None
    bundled_root = str(summary.get("bundled_payload_root") or "") or None
    if require_source_kind and source_kind != require_source_kind:
        raise RuntimeError(
            f"{label} expected source_kind={require_source_kind}, got {source_kind or 'missing'}"
        )
    if require_bundled_source and source_kind not in {"bundled_packaged", "bundled_dev"}:
        raise RuntimeError(
            f"{label} expected bundled source ownership, got {source_kind or 'missing'}"
        )
    if require_bundled_source and not bundled_root:
        raise RuntimeError(f"{label} expected bundled payload root, but none was recorded")


def main() -> int:
    parser = argparse.ArgumentParser(description="Release-grade smoke for managed Stanza runtime")
    parser.add_argument(
        "--db-path",
        type=str,
        default="",
        help="Optional source DB for document-scoped smoke clone before re-process",
    )
    parser.add_argument(
        "--copy-db-to",
        type=str,
        default="",
        help="Target path for the small document-scoped smoke DB",
    )
    parser.add_argument("--doc-id", type=int, default=1, help="Document ID for DB smoke re-process")
    parser.add_argument(
        "--sample-text",
        type=str,
        default="הילד הגדול קורא ספר חדש.",
        help="Hebrew sample text for direct engine smoke",
    )
    parser.add_argument(
        "--force-hostile-inprocess",
        action="store_true",
        help="Force direct in-process Stanza init failure while validating managed subprocess recovery",
    )
    parser.add_argument(
        "--require-source-kind",
        type=str,
        default="",
        help="Require a specific managed source ownership kind such as bundled_packaged or bundled_dev.",
    )
    parser.add_argument(
        "--require-bundled-source",
        action="store_true",
        help="Fail if the smoke uses a non-bundled managed payload source.",
    )
    args = parser.parse_args()

    report: dict[str, object] = {
        "engine_smoke": _run_engine_smoke(
            sample_text=args.sample_text,
            force_hostile=bool(args.force_hostile_inprocess),
        )
    }
    _assert_expected_source(
        report["engine_smoke"],
        label="engine_smoke",
        require_source_kind=str(args.require_source_kind or "") or None,
        require_bundled_source=bool(args.require_bundled_source),
    )

    if args.db_path:
        source_db = Path(args.db_path).expanduser().resolve()
        copy_target = (
            Path(args.copy_db_to).expanduser().resolve()
            if args.copy_db_to
            else Path("reports/runtime_smoke/runtime_smoke_copy.db").resolve()
        )
        report["db_reprocess_smoke"] = _run_db_smoke(
            source_db=source_db,
            copy_db_to=copy_target,
            doc_id=int(args.doc_id),
        )
        _assert_expected_source(
            report["db_reprocess_smoke"],
            label="db_reprocess_smoke",
            require_source_kind=str(args.require_source_kind or "") or None,
            require_bundled_source=bool(args.require_bundled_source),
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
