"""Release-grade smoke validation for the managed Windows Stanza runtime."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from sqlalchemy import func, select

from app.infra.nlp_engines.stanza_engine import StanzaEngine, create_stanza_engine
from app.infra.sa_models import ProcessorRun, SourceDocument
from app.services.db_service import DBService
from app.services.process_service import ProcessService


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _copy_db(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


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

    return summary


def _run_db_smoke(*, source_db: Path, copy_db_to: Path, doc_id: int) -> dict[str, object]:
    _copy_db(source_db, copy_db_to)

    DBService.shutdown()
    DBService._instance = None
    DBService._db_manager = None
    DBService._ref_managers = {}
    DBService.initialize(copy_db_to)
    db = DBService.get_instance()
    service = ProcessService()

    try:
        with db.get_session() as session:
            doc = session.get(SourceDocument, int(doc_id))
            if doc is None:
                raise RuntimeError(f"Document not found in DB copy: {doc_id}")

            before_run_id = session.execute(select(func.max(ProcessorRun.run_id))).scalar_one()
            before_run_id = int(before_run_id or 0)

            ok = service.reprocess_document(
                session,
                int(doc_id),
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

            return {
                "db_copy": str(copy_db_to),
                "doc_id": int(doc_id),
                "ok": bool(ok),
                "document_status": str(doc.status),
                "run_engine": str(latest_run.engine) if latest_run is not None else None,
                "run_status": str(latest_run.status) if latest_run is not None else None,
                "runtime_effective": _extract_runtime_effective(latest_run.note) if latest_run is not None else None,
                "created_run_id": int(latest_run.run_id) if latest_run is not None else None,
            }
    finally:
        DBService.shutdown()
        DBService._instance = None
        DBService._db_manager = None
        DBService._ref_managers = {}


def _extract_runtime_effective(note_text: str | None) -> str | None:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Release-grade smoke for managed Stanza runtime")
    parser.add_argument("--db-path", type=str, default="", help="Optional source DB to copy and re-process")
    parser.add_argument("--copy-db-to", type=str, default="", help="Target path for DB smoke copy")
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
    args = parser.parse_args()

    report: dict[str, object] = {
        "engine_smoke": _run_engine_smoke(
            sample_text=args.sample_text,
            force_hostile=bool(args.force_hostile_inprocess),
        )
    }

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

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
