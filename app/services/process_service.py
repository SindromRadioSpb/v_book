"""Document processing service."""

import contextlib
import hashlib
import inspect
import json
import logging
import math
import sqlite3
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.domain.dto import NLPProcessRunState
from app.domain.preprocessing import preprocess_text
from app.domain.sentence_splitter import split_into_sentences
from app.infra.nlp_engines.base import NLPEngine
from app.infra.nlp_engines.stanza_engine import create_stanza_engine
from app.infra.nlp_snapshot_codec import (
    build_sentence_text_hash,
    count_snapshot_tokens,
    serialize_nlp_sentences,
)
from app.infra.sa_models import (
    DictProject,
    DocumentSentence,
    DocumentText,
    Lemma,
    LemmaDocStat,
    LemmaProjectStat,
    ProcessorRun,
    RunError,
    SentenceNLPSnapshot,
    SentenceNLPSnapshotStage,
    SourceDocument,
)
from app.services.db_service import DBService
from app.services.entity_classifier import classify_text
from app.services.nlp_runtime import NlpRuntimeProbe, NlpRuntimeStatus
from app.services.snapshot_doc_stats_service import SnapshotDocStatsService

logger = logging.getLogger(__name__)

SNAPSHOT_BOUNDED_VALIDATION_MIN_DOCS = 10_000


class ProcessService:
    """Service for NLP document processing."""

    def __init__(self):
        self.db_service = DBService.get_instance()
        self._engine: NLPEngine | None = None
        self._engine_key: tuple[str, bool] | None = None
        self.snapshot_doc_stats_service = SnapshotDocStatsService()
        self.runtime_probe = NlpRuntimeProbe()
        logger.info("ProcessService initialized")

    def get_nlp_engine(self, use_gpu: bool = False, use_mock: bool = False) -> NLPEngine:
        """
        Get or create NLP engine (singleton).

        Args:
            use_gpu: Whether to use GPU
            use_mock: Use mock engine instead of Stanza (for testing)

        Returns:
            NLPEngine instance

        Raises:
            RuntimeError: If engine initialization fails
        """
        desired_key = ("mock" if use_mock else "stanza", bool(use_gpu) if not use_mock else False)
        if self._engine is None or self._engine_key != desired_key:
            if use_mock:
                logger.info("Creating Mock NLP engine (diagnostic/explicit-fallback)...")
                from app.infra.nlp_engines.mock_engine import create_mock_engine

                self._engine = create_mock_engine()
            else:
                logger.info("Creating Stanza NLP engine...")
                self._engine = create_stanza_engine(use_gpu=use_gpu)
            self._engine_key = desired_key

            logger.info(
                f"NLP engine ready: {self._engine.get_name()} v{self._engine.get_version()}"
            )
        return self._engine

    def _build_run_params_hash(
        self,
        *,
        engine: NLPEngine,
        configured_engine_id: str,
        effective_engine_id: str,
        use_gpu: bool,
        use_mock: bool,
        fallback_used: bool,
        is_reprocess: bool,
        contract: str = "process_document_v2",
    ) -> str:
        payload = {
            "contract": str(contract or "process_document_v2"),
            "configured_engine_id": str(configured_engine_id or engine.get_name()),
            "effective_engine_id": str(effective_engine_id or engine.get_name()),
            "engine": engine.get_name(),
            "engine_version": engine.get_version(),
            "use_gpu": bool(use_gpu),
            "use_mock": bool(use_mock),
            "fallback_used": bool(fallback_used),
            "is_reprocess": bool(is_reprocess),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _build_runtime_provenance_payload(
        *,
        runtime_status: NlpRuntimeStatus,
        use_gpu: bool,
        use_mock: bool,
        is_reprocess: bool,
        source_label: str,
        kind: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": kind,
            "source": str(source_label or "unknown"),
            "configured_engine_id": runtime_status.configured_engine_id,
            "effective_engine_id": runtime_status.effective_engine_id,
            "fallback_used": bool(runtime_status.fallback_used),
            "reason_code": runtime_status.error_code,
            "runtime_mode": runtime_status.runtime_mode,
            "use_gpu": bool(use_gpu),
            "use_mock": bool(use_mock),
            "is_reprocess": bool(is_reprocess),
            "probe_summary": {
                "package_installed": bool(runtime_status.package_installed),
                "model_present": bool(runtime_status.model_present),
                "pipeline_init_ok": bool(runtime_status.pipeline_init_ok),
                "smoke_ok": bool(runtime_status.smoke_ok),
                "error_detail": runtime_status.error_detail,
                "engine_version": runtime_status.engine_version,
                "model_id": runtime_status.model_id,
                "model_path": runtime_status.model_path,
            },
        }

    @staticmethod
    def _build_runtime_note_payload(
        *,
        runtime_status: NlpRuntimeStatus,
        use_gpu: bool,
        use_mock: bool,
        is_reprocess: bool,
        source_label: str,
        kind: str,
    ) -> dict[str, Any]:
        payload = {
            "kind": kind,
            "source": str(source_label or "unknown"),
            "configured_engine_id": runtime_status.configured_engine_id,
            "effective_engine_id": runtime_status.effective_engine_id,
            "fallback_used": bool(runtime_status.fallback_used),
            "runtime_mode": runtime_status.runtime_mode,
            "engine_version": runtime_status.engine_version,
            "model_id": runtime_status.model_id,
            "model_path": runtime_status.model_path,
            "package_installed": bool(runtime_status.package_installed),
            "model_present": bool(runtime_status.model_present),
            "pipeline_init_ok": bool(runtime_status.pipeline_init_ok),
            "smoke_ok": bool(runtime_status.smoke_ok),
            "error_code": runtime_status.error_code,
            "error_detail": runtime_status.error_detail,
            "use_gpu": bool(use_gpu),
            "use_mock": bool(use_mock),
            "is_reprocess": bool(is_reprocess),
        }
        payload["runtime"] = ProcessService._build_runtime_provenance_payload(
            runtime_status=runtime_status,
            use_gpu=use_gpu,
            use_mock=use_mock,
            is_reprocess=is_reprocess,
            source_label=source_label,
            kind=kind,
        )
        return payload

    def _build_single_run_note(
        self,
        *,
        runtime_status: NlpRuntimeStatus,
        use_gpu: bool,
        use_mock: bool,
        is_reprocess: bool,
        source_label: str = "single_document",
    ) -> str:
        payload = self._build_runtime_note_payload(
            runtime_status=runtime_status,
            use_gpu=use_gpu,
            use_mock=use_mock,
            is_reprocess=is_reprocess,
            source_label=source_label,
            kind="single_nlp",
        )
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def _resolve_nlp_runtime(
        self,
        *,
        use_gpu: bool,
        use_mock: bool,
        configured_engine_id: str | None,
        allow_mock_fallback: bool,
    ) -> tuple[NLPEngine, NlpRuntimeStatus]:
        configured = str(configured_engine_id or ("mock" if use_mock else "stanza")).strip().lower()
        if configured == "mock":
            return (
                self.get_nlp_engine(use_gpu=False, use_mock=True),
                self.runtime_probe.build_mock_status(configured_engine_id="mock"),
            )

        stanza_status = self.runtime_probe.probe_stanza(use_gpu=use_gpu, run_smoke=True)
        if not use_mock:
            if not stanza_status.stanza_ready:
                raise RuntimeError(self._format_runtime_block_message(stanza_status))
            try:
                return self.get_nlp_engine(use_gpu=use_gpu, use_mock=False), stanza_status
            except Exception as exc:
                failure_code = (
                    "hostile_torch_state" if isinstance(exc, OSError) else "runtime_import_failed"
                )
                failure_status = NlpRuntimeStatus(
                    configured_engine_id="stanza",
                    effective_engine_id=None,
                    package_installed=True,
                    model_present=stanza_status.model_present,
                    pipeline_init_ok=False,
                    smoke_ok=False,
                    cuda_available=stanza_status.cuda_available,
                    runtime_mode=stanza_status.runtime_mode,
                    fallback_used=False,
                    error_code=failure_code,
                    error_detail=str(exc),
                    remediation=stanza_status.remediation,
                    engine_version=stanza_status.engine_version,
                    model_id=stanza_status.model_id,
                    model_path=stanza_status.model_path,
                )
                raise RuntimeError(self._format_runtime_block_message(failure_status)) from exc

        if not allow_mock_fallback:
            raise RuntimeError("Explicit mock fallback is disabled for this processing request.")

        return (
            self.get_nlp_engine(use_gpu=False, use_mock=True),
            NlpRuntimeStatus(
                configured_engine_id="stanza",
                effective_engine_id="mock",
                package_installed=stanza_status.package_installed,
                model_present=stanza_status.model_present,
                pipeline_init_ok=stanza_status.pipeline_init_ok,
                smoke_ok=stanza_status.smoke_ok,
                cuda_available=stanza_status.cuda_available,
                runtime_mode="cpu",
                fallback_used=True,
                error_code=stanza_status.error_code or "fallback_requested",
                error_detail=stanza_status.error_detail,
                remediation=(
                    "Mock runtime is active only because the user explicitly confirmed fallback."
                ),
                engine_version="1.0.0",
                model_id=stanza_status.model_id,
                model_path=stanza_status.model_path,
            ),
        )

    @staticmethod
    def _format_runtime_block_message(status: NlpRuntimeStatus) -> str:
        detail = str(status.error_detail or "").strip()
        suffix = f"\n\nDetails: {detail[:300]}" if detail else ""
        if status.error_code == "package_missing":
            return (
                "Stanza runtime is not installed in the active environment.\n\n"
                "Install the Python package and retry, or explicitly confirm Mock fallback."
                f"{suffix}"
            )
        if status.error_code == "model_missing":
            return (
                "Stanza package is present, but the Hebrew model resources are missing.\n\n"
                "Install or import the Hebrew model and retry, or explicitly confirm Mock fallback."
                f"{suffix}"
            )
        if status.error_code == "smoke_failed":
            return (
                "Stanza initialized but failed the smoke test.\n\n"
                "Inspect the runtime environment or explicitly confirm Mock fallback."
                f"{suffix}"
            )
        if status.error_code in {"hostile_torch_state", "runtime_import_failed"}:
            return (
                "Stanza probe reported ready, but live engine initialization failed in the current process.\n\n"
                "Fix the local Torch/Stanza runtime or explicitly confirm Mock fallback."
                f"{suffix}"
            )
        return (
            "Stanza runtime is unavailable for persisted processing.\n\n"
            "Fix the runtime or explicitly confirm Mock fallback."
            f"{suffix}"
        )

    @staticmethod
    def _build_doc_ids_hash(doc_ids: list[int]) -> str:
        encoded = json.dumps([int(doc_id) for doc_id in doc_ids], separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def _build_run_state_payload(
        self,
        run: ProcessorRun,
        *,
        phase: str,
        message: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        payload = asdict(
            NLPProcessRunState(
                run_id=int(run.run_id),
                project_id=int(run.project_id),
                status=str(run.status),
                stage=run.stage,
                docs_total=int(run.docs_total or 0),
                docs_processed=int(run.docs_processed or 0),
                docs_failed=int(run.docs_failed or 0),
                chunks_total=int(run.chunks_total or 0),
                chunks_completed=int(run.chunks_completed or 0),
                last_doc_id=int(run.last_doc_id) if run.last_doc_id is not None else None,
                params_hash=run.params_hash,
                error_message=run.error_message,
            )
        )
        payload["phase"] = phase
        if message is not None:
            payload["message"] = message
        if doc_name is not None:
            payload["doc_name"] = doc_name
        return payload

    def _emit_run_state(
        self,
        state_callback: Callable[[dict[str, Any]], None] | None,
        run: ProcessorRun,
        *,
        phase: str,
        message: str | None = None,
        doc_name: str | None = None,
    ) -> None:
        if state_callback is None:
            return
        state_callback(
            self._build_run_state_payload(
                run,
                phase=phase,
                message=message,
                doc_name=doc_name,
            )
        )

    @staticmethod
    def _build_batch_run_note(
        *,
        doc_ids: list[int],
        chunk_size: int,
        source_label: str,
        is_reprocess: bool,
        extra_note: dict[str, Any] | None = None,
    ) -> str:
        note = {
            "kind": "batch_nlp",
            "source": source_label,
            "chunk_size": int(chunk_size),
            "doc_count": len(doc_ids),
            "first_doc_id": int(doc_ids[0]),
            "last_doc_id": int(doc_ids[-1]),
            "doc_ids_hash": ProcessService._build_doc_ids_hash(doc_ids),
            "is_reprocess": bool(is_reprocess),
        }
        if extra_note:
            note.update(extra_note)
        return json.dumps(note, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _parse_batch_run_note(note: str | None) -> dict[str, Any]:
        if not note:
            return {}
        try:
            payload = json.loads(note)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _find_batch_run_candidate(
        self,
        session: Session,
        *,
        project_id: int,
        params_hash: str,
        doc_ids: list[int],
        source_label: str,
        is_reprocess: bool,
    ) -> ProcessorRun | None:
        candidates = (
            session.query(ProcessorRun)
            .filter(
                ProcessorRun.project_id == project_id,
                ProcessorRun.params_hash == params_hash,
                ProcessorRun.status.in_(("paused", "cancelled", "failed")),
            )
            .order_by(ProcessorRun.run_id.desc())
            .limit(20)
            .all()
        )
        for run in candidates:
            ok, _reason, _note = self._verify_batch_run_contract(
                run,
                project_id=project_id,
                params_hash=params_hash,
                doc_ids=doc_ids,
                source_label=source_label,
                is_reprocess=is_reprocess,
                require_incomplete=True,
            )
            if not ok:
                continue
            return run
        return None

    def _verify_batch_run_contract(
        self,
        run: ProcessorRun,
        *,
        project_id: int,
        params_hash: str,
        doc_ids: list[int],
        source_label: str,
        is_reprocess: bool,
        require_incomplete: bool,
    ) -> tuple[bool, str | None, dict[str, Any]]:
        note = self._parse_batch_run_note(run.note)
        if note.get("kind") != "batch_nlp":
            return False, "Run note is not a batch NLP contract", note
        if int(run.project_id or 0) != int(project_id):
            return False, "Run project does not match the requested document slice", note
        if str(run.params_hash or "") != str(params_hash or ""):
            return False, "Run params_hash does not match the requested engine contract", note
        if note.get("source") != source_label:
            return False, "Run source label does not match this processing entry point", note
        if bool(note.get("is_reprocess")) != bool(is_reprocess):
            return False, "Run reprocess flag does not match the requested mode", note
        if int(note.get("doc_count") or 0) != len(doc_ids):
            return False, "Run document count does not match the requested document slice", note
        if int(note.get("first_doc_id") or 0) != int(doc_ids[0]):
            return False, "Run first_doc_id does not match the requested document slice", note
        if int(note.get("last_doc_id") or 0) != int(doc_ids[-1]):
            return False, "Run last_doc_id does not match the requested document slice", note
        if str(note.get("doc_ids_hash") or "") != self._build_doc_ids_hash(doc_ids):
            return False, "Run doc_ids_hash does not match the requested document slice", note
        if int(run.docs_total or 0) != len(doc_ids):
            return False, "Run docs_total does not match the requested document slice", note
        if require_incomplete:
            if str(run.status or "") not in {"paused", "cancelled", "failed"}:
                return (
                    False,
                    f"Run {int(run.run_id)} status '{run.status}' is not resumable",
                    note,
                )
            if int((run.docs_processed or 0) + (run.docs_failed or 0)) >= int(run.docs_total or 0):
                return False, f"Run {int(run.run_id)} has no remaining documents to resume", note
        return True, None, note

    def verify_batch_run_contract(
        self,
        session: Session,
        doc_ids: list[int],
        use_gpu: bool = False,
        use_mock: bool = False,
        configured_engine_id: str | None = None,
        allow_mock_fallback: bool = False,
        *,
        is_reprocess: bool = False,
        source_label: str = "batch",
        resume_latest: bool = False,
        resume_run_id: int | None = None,
        contract: str = "process_document_v2",
    ) -> dict[str, Any]:
        """Validate a batch NLP run contract without mutating the DB."""
        if resume_latest and resume_run_id is not None:
            raise ValueError("resume_latest and resume_run_id are mutually exclusive")

        ordered_ids = sorted({int(doc_id) for doc_id in doc_ids})
        if not ordered_ids:
            raise ValueError("doc_ids must not be empty")

        project_id = self._resolve_project_id_for_docs(session, ordered_ids)
        engine, runtime_status = self._resolve_nlp_runtime(
            use_gpu=use_gpu,
            use_mock=use_mock,
            configured_engine_id=configured_engine_id,
            allow_mock_fallback=allow_mock_fallback,
        )
        params_hash = self._build_run_params_hash(
            engine=engine,
            configured_engine_id=runtime_status.configured_engine_id,
            effective_engine_id=runtime_status.effective_engine_id or engine.get_name(),
            use_gpu=use_gpu,
            use_mock=use_mock,
            fallback_used=runtime_status.fallback_used,
            is_reprocess=is_reprocess,
            contract=contract,
        )
        report: dict[str, Any] = {
            "ok": False,
            "mode": "fresh",
            "project_id": project_id,
            "doc_count": len(ordered_ids),
            "doc_ids_hash": self._build_doc_ids_hash(ordered_ids),
            "params_hash": params_hash,
            "source_label": source_label,
            "is_reprocess": bool(is_reprocess),
            "run_id": None,
            "status": None,
            "stage": None,
            "remaining_docs": len(ordered_ids),
            "chunk_size": None,
            "reason": None,
        }

        if resume_run_id is None and not resume_latest:
            report["ok"] = True
            return report

        if resume_run_id is not None:
            run = session.get(ProcessorRun, int(resume_run_id))
            if run is None:
                report["mode"] = "resume_run_id"
                report["reason"] = f"Run {int(resume_run_id)} was not found"
                return report
            report["mode"] = "resume_run_id"
        else:
            run = self._find_batch_run_candidate(
                session,
                project_id=project_id,
                params_hash=params_hash,
                doc_ids=ordered_ids,
                source_label=source_label,
                is_reprocess=is_reprocess,
            )
            report["mode"] = "resume_latest"
            if run is None:
                report["reason"] = "No matching incomplete NLP batch run was found"
                return report

        ok, reason, note = self._verify_batch_run_contract(
            run,
            project_id=project_id,
            params_hash=params_hash,
            doc_ids=ordered_ids,
            source_label=source_label,
            is_reprocess=is_reprocess,
            require_incomplete=True,
        )
        report.update(
            {
                "run_id": int(run.run_id),
                "status": str(run.status or ""),
                "stage": run.stage,
                "remaining_docs": max(
                    0,
                    int(run.docs_total or 0)
                    - int(run.docs_processed or 0)
                    - int(run.docs_failed or 0),
                ),
                "chunk_size": int(note.get("chunk_size") or 0) or None,
                "reason": reason,
            }
        )
        report["ok"] = bool(ok)
        return report

    def _resolve_project_id_for_docs(self, session: Session, doc_ids: list[int]) -> int:
        doc = session.get(SourceDocument, int(doc_ids[0]))
        if doc is None:
            raise ValueError(f"Document {doc_ids[0]} not found")

        from app.infra.sa_models import SourceCorpus

        corpus = session.get(SourceCorpus, int(doc.corpus_id))
        if corpus is None:
            raise ValueError(f"Corpus {doc.corpus_id} not found for document {doc_ids[0]}")
        project_id = int(corpus.project_id)

        for doc_id in doc_ids[1:]:
            other_doc = session.get(SourceDocument, int(doc_id))
            if other_doc is None:
                raise ValueError(f"Document {doc_id} not found")
            other_corpus = session.get(SourceCorpus, int(other_doc.corpus_id))
            if other_corpus is None:
                raise ValueError(f"Corpus {other_doc.corpus_id} not found for document {doc_id}")
            if int(other_corpus.project_id) != project_id:
                raise ValueError("All documents in a batch run must belong to the same project")

        return project_id

    def _build_sentence_nlp_snapshot_values(
        self,
        *,
        sentence_row: DocumentSentence,
        engine: NLPEngine,
        nlp_sentences: list[Any],
    ) -> dict[str, Any]:
        now = self._utc_now()
        return {
            "sentence_id": int(sentence_row.sentence_id),
            "engine": engine.get_name(),
            "engine_version": engine.get_version(),
            "sentence_text_hash": build_sentence_text_hash(str(sentence_row.text or "")),
            "payload_json": serialize_nlp_sentences(nlp_sentences),
            "token_count": count_snapshot_tokens(nlp_sentences),
            "created_at": now,
            "updated_at": now,
        }

    def _upsert_sentence_nlp_snapshot(
        self,
        session: Session,
        *,
        sentence_row: DocumentSentence,
        engine: NLPEngine,
        nlp_sentences: list[Any],
    ) -> int:
        values = self._build_sentence_nlp_snapshot_values(
            sentence_row=sentence_row,
            engine=engine,
            nlp_sentences=nlp_sentences,
        )
        snapshot = session.get(SentenceNLPSnapshot, int(sentence_row.sentence_id))
        if snapshot is None:
            snapshot = SentenceNLPSnapshot(sentence_id=int(sentence_row.sentence_id))
            session.add(snapshot)

        snapshot.engine = str(values["engine"])
        snapshot.engine_version = values["engine_version"]
        snapshot.sentence_text_hash = str(values["sentence_text_hash"])
        snapshot.payload_json = str(values["payload_json"])
        snapshot.token_count = int(values["token_count"] or 0)
        return int(snapshot.token_count or 0)

    def _record_batch_run_error(
        self,
        session: Session,
        *,
        run_id: int | None,
        doc_id: int | None,
        stage: str,
        message: str,
    ) -> None:
        if run_id is None:
            return
        session.add(
            RunError(
                run_id=int(run_id),
                doc_id=int(doc_id) if doc_id is not None else None,
                stage=str(stage or "batch"),
                message=str(message or "")[:500],
            )
        )

    def _clear_sentence_nlp_snapshot_stage(self, session: Session, *, run_id: int) -> int:
        stage_count = int(
            session.execute(
                select(text("COUNT(*)"))
                .select_from(SentenceNLPSnapshotStage)
                .where(SentenceNLPSnapshotStage.run_id == int(run_id))
            ).scalar()
            or 0
        )
        if stage_count <= 0:
            return 0
        session.execute(
            SentenceNLPSnapshotStage.__table__.delete().where(
                SentenceNLPSnapshotStage.run_id == int(run_id)
            )
        )
        session.flush()
        return stage_count

    def _stage_sentence_nlp_snapshot_rows(
        self,
        session: Session,
        *,
        run_id: int,
        rows: list[dict[str, Any]],
        insert_batch_size: int = 200,
    ) -> int:
        if not rows:
            return 0

        inserted = 0
        for start in range(0, len(rows), int(insert_batch_size)):
            chunk = []
            for row in rows[start : start + int(insert_batch_size)]:
                chunk.append(
                    {
                        "run_id": int(run_id),
                        "sentence_id": int(row["sentence_id"]),
                        "engine": str(row["engine"]),
                        "engine_version": row.get("engine_version"),
                        "sentence_text_hash": str(row["sentence_text_hash"]),
                        "payload_json": str(row["payload_json"]),
                        "token_count": int(row["token_count"] or 0),
                        "created_at": row.get("created_at") or self._utc_now(),
                        "updated_at": row.get("updated_at") or self._utc_now(),
                    }
                )
            stmt = sqlite_insert(SentenceNLPSnapshotStage.__table__).values(chunk)
            excluded = stmt.excluded
            stmt = stmt.on_conflict_do_update(
                index_elements=["run_id", "sentence_id"],
                set_={
                    "engine": excluded.engine,
                    "engine_version": excluded.engine_version,
                    "sentence_text_hash": excluded.sentence_text_hash,
                    "payload_json": excluded.payload_json,
                    "token_count": excluded.token_count,
                    "updated_at": excluded.updated_at,
                },
            )
            session.execute(stmt)
            inserted += len(chunk)

        session.flush()
        return inserted

    def _merge_sentence_nlp_snapshot_stage(
        self,
        session: Session,
        *,
        run_id: int,
        merge_batch_size: int,
    ) -> int:
        merged = 0
        batch_size = max(1, int(merge_batch_size or 1000))

        while True:
            rows = [
                dict(row)
                for row in session.execute(
                    select(
                        SentenceNLPSnapshotStage.sentence_id,
                        SentenceNLPSnapshotStage.engine,
                        SentenceNLPSnapshotStage.engine_version,
                        SentenceNLPSnapshotStage.sentence_text_hash,
                        SentenceNLPSnapshotStage.payload_json,
                        SentenceNLPSnapshotStage.token_count,
                        SentenceNLPSnapshotStage.created_at,
                        SentenceNLPSnapshotStage.updated_at,
                    )
                    .where(SentenceNLPSnapshotStage.run_id == int(run_id))
                    .order_by(SentenceNLPSnapshotStage.sentence_id.asc())
                    .limit(batch_size)
                )
                .mappings()
                .all()
            ]
            if not rows:
                return merged

            sentence_ids = [int(row["sentence_id"]) for row in rows]
            stmt = sqlite_insert(SentenceNLPSnapshot.__table__).values(rows)
            excluded = stmt.excluded
            stmt = stmt.on_conflict_do_update(
                index_elements=["sentence_id"],
                set_={
                    "engine": excluded.engine,
                    "engine_version": excluded.engine_version,
                    "sentence_text_hash": excluded.sentence_text_hash,
                    "payload_json": excluded.payload_json,
                    "token_count": excluded.token_count,
                    "updated_at": excluded.updated_at,
                },
            )
            session.execute(stmt)
            session.execute(
                SentenceNLPSnapshotStage.__table__.delete().where(
                    SentenceNLPSnapshotStage.run_id == int(run_id),
                    SentenceNLPSnapshotStage.sentence_id.in_(sentence_ids),
                )
            )
            session.commit()
            merged += len(rows)

    def _run_snapshot_backfill_segment_check(
        self,
        *,
        quick_check_timeout_sec: float = 0.5,
    ) -> dict[str, Any]:
        """Run a bounded physical check between super-chunks.

        Timeout is treated as inconclusive-but-not-failing; direct table probes
        must still succeed.
        """
        db_path = self.db_service.db_manager.db_path
        summary: dict[str, Any] = {
            "ok": False,
            "db_path": str(db_path),
            "quick_check_rows": [],
            "quick_check_timed_out": False,
            "quick_check_timeout_sec": float(quick_check_timeout_sec),
            "snapshot_probe_error": None,
            "error": None,
        }
        conn: sqlite3.Connection | None = None
        started = time.perf_counter()

        def _progress_handler() -> int:
            if quick_check_timeout_sec <= 0:
                return 0
            elapsed = time.perf_counter() - started
            return 1 if elapsed >= float(quick_check_timeout_sec) else 0

        try:
            conn = sqlite3.connect(str(db_path), timeout=30)
            conn.execute("PRAGMA busy_timeout=15000")
            conn.set_progress_handler(_progress_handler, 10_000)
            try:
                quick_rows = [
                    str(row[0]) for row in conn.execute("PRAGMA quick_check(10)").fetchall()
                ]
            except sqlite3.OperationalError as exc:
                if "interrupted" in str(exc).lower() and quick_check_timeout_sec > 0:
                    summary["quick_check_timed_out"] = True
                    quick_rows = []
                else:
                    raise
            finally:
                conn.set_progress_handler(None, 0)

            summary["quick_check_rows"] = quick_rows
            if quick_rows and any(str(row).lower() != "ok" for row in quick_rows):
                summary["error"] = "PRAGMA quick_check(10) failed: " + "; ".join(quick_rows[:5])
                return summary

            conn.execute(
                "SELECT sentence_id FROM sentence_nlp_snapshot ORDER BY sentence_id DESC LIMIT 1"
            ).fetchone()
            summary["ok"] = True
            return summary
        except sqlite3.Error as exc:
            summary["snapshot_probe_error"] = str(exc)
            summary["error"] = str(exc)
            return summary
        finally:
            if conn is not None:
                with contextlib.suppress(sqlite3.Error):
                    conn.close()

    def _run_snapshot_backfill_integrity_check(
        self,
        *,
        checkpoint_mode: str = "none",
    ) -> dict[str, Any]:
        """Verify physical DB integrity before marking snapshot backfill as successful."""
        db_path = self.db_service.db_manager.db_path
        normalized_checkpoint_mode = str(checkpoint_mode or "none").strip().lower()
        if normalized_checkpoint_mode not in {"truncate", "passive", "full", "restart", "none"}:
            raise ValueError(f"Unsupported integrity checkpoint mode: {checkpoint_mode}")
        summary: dict[str, Any] = {
            "ok": False,
            "db_path": str(db_path),
            "checkpoint_mode": normalized_checkpoint_mode,
            "checkpoint": None,
            "quick_check_rows": [],
            "snapshot_probe_error": None,
            "error": None,
        }
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(str(db_path), timeout=30)
            conn.execute("PRAGMA busy_timeout=15000")
            if normalized_checkpoint_mode != "none":
                checkpoint_row = conn.execute(
                    f"PRAGMA wal_checkpoint({normalized_checkpoint_mode.upper()})"
                ).fetchone()
                if checkpoint_row is not None:
                    summary["checkpoint"] = [int(value) for value in checkpoint_row]
            quick_rows = [str(row[0]) for row in conn.execute("PRAGMA quick_check(10)").fetchall()]
            summary["quick_check_rows"] = quick_rows
            if not quick_rows or any(str(row).lower() != "ok" for row in quick_rows):
                summary["error"] = (
                    "PRAGMA quick_check(10) failed: " + "; ".join(quick_rows[:5])
                    if quick_rows
                    else "PRAGMA quick_check(10) returned no rows"
                )
                return summary

            conn.execute(
                "SELECT sentence_id FROM sentence_nlp_snapshot ORDER BY sentence_id DESC LIMIT 1"
            ).fetchone()
            summary["ok"] = True
            return summary
        except sqlite3.Error as exc:
            summary["snapshot_probe_error"] = str(exc)
            if summary["error"] is None:
                summary["error"] = str(exc)
            return summary
        finally:
            if conn is not None:
                with contextlib.suppress(sqlite3.Error):
                    conn.close()

    def _finalize_snapshot_backfill_run(
        self,
        session: Session,
        *,
        run: ProcessorRun,
        success: int,
        errors: int,
        integrity_checkpoint_mode: str = "none",
        state_callback: Callable[[dict[str, Any]], None] | None = None,
        completion_message: str,
    ) -> tuple[int, int]:
        run.stage = "integrity_check"
        session.commit()
        session.refresh(run)
        self._emit_run_state(
            state_callback,
            run,
            phase="verifying_integrity",
            message="Running post-backfill integrity verification",
        )

        integrity = self._run_snapshot_backfill_integrity_check(
            checkpoint_mode=integrity_checkpoint_mode,
        )
        if not integrity.get("ok"):
            failure_message = str(
                integrity.get("error") or "Sentence snapshot backfill integrity verification failed"
            )[:500]
            try:
                self._record_batch_run_error(
                    session,
                    run_id=int(run.run_id),
                    doc_id=None,
                    stage="integrity_check",
                    message=failure_message,
                )
                run.status = "failed"
                run.stage = "failed_integrity"
                run.finished_at = self._utc_now()
                run.error_message = failure_message
                session.commit()
                session.refresh(run)
            except Exception:
                session.rollback()
                logger.exception(
                    "Failed to persist integrity failure state for snapshot backfill run %s",
                    int(run.run_id),
                )
            self._emit_run_state(
                state_callback,
                run,
                phase="failed",
                message=failure_message,
            )
            raise RuntimeError(failure_message)

        run.status = "ok"
        run.stage = "completed_with_errors" if errors > 0 else "completed"
        run.finished_at = self._utc_now()
        run.chunks_completed = int(run.chunks_total or 0)
        run.error_message = (
            f"{errors} document(s) failed during sentence snapshot backfill" if errors > 0 else None
        )
        session.commit()
        session.refresh(run)
        self._emit_run_state(
            state_callback,
            run,
            phase="completed",
            message=completion_message,
        )

        logger.info(
            "Sentence snapshot backfill complete: %d succeeded, %d failed (run_id=%d)",
            success,
            errors,
            int(run.run_id),
        )
        return success, errors

    def _start_processor_run(
        self,
        session: Session,
        *,
        project_id: int,
        engine: NLPEngine,
        runtime_status: NlpRuntimeStatus,
        doc_id: int,
        use_gpu: bool,
        use_mock: bool,
        is_reprocess: bool,
    ) -> ProcessorRun:
        run = ProcessorRun(
            project_id=project_id,
            engine=engine.get_name(),
            engine_version=engine.get_version(),
            docs_total=1,
            docs_processed=0,
            docs_failed=0,
            chunks_total=1,
            chunks_completed=0,
            status="running",
            stage="processing",
            last_doc_id=doc_id,
            params_hash=self._build_run_params_hash(
                engine=engine,
                configured_engine_id=runtime_status.configured_engine_id,
                effective_engine_id=runtime_status.effective_engine_id or engine.get_name(),
                use_gpu=use_gpu,
                use_mock=use_mock,
                fallback_used=runtime_status.fallback_used,
                is_reprocess=is_reprocess,
            ),
            note=self._build_single_run_note(
                runtime_status=runtime_status,
                use_gpu=use_gpu,
                use_mock=use_mock,
                is_reprocess=is_reprocess,
            ),
        )
        session.add(run)
        session.flush()
        return run

    def process_document(
        self,
        session: Session,
        doc_id: int,
        use_gpu: bool = False,
        use_mock: bool = False,
        configured_engine_id: str | None = None,
        allow_mock_fallback: bool = False,
        is_reprocess: bool = False,
        track_run: bool = True,
        batch_run_id: int | None = None,
    ) -> bool:
        """
        Process a document with NLP pipeline.

        Steps:
        1. Get raw text
        2. Preprocess
        3. Split into sentences
        4. NLP (tokenize + lemmatize + POS)
        5. Store sentences
        6. Calculate lemma statistics
        7. Update document status

        Args:
            session: Database session
            doc_id: Document ID
            use_gpu: Whether to use GPU for NLP
            use_mock: Use mock engine instead of Stanza
            is_reprocess: Mark the run as a re-processing invocation for
                params-hash/state tracking
            track_run: Whether to create/update a dedicated per-document run row
            batch_run_id: Optional batch-level run ID for shared error logging

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Processing document {doc_id}...")

        # Get document
        doc = session.get(SourceDocument, doc_id)
        if not doc:
            logger.error(f"Document not found: {doc_id}")
            return False

        # Get project
        from app.infra.sa_models import SourceCorpus

        corpus = session.get(SourceCorpus, doc.corpus_id)
        project_id = corpus.project_id

        # Start processor run
        engine, runtime_status = self._resolve_nlp_runtime(
            use_gpu=use_gpu,
            use_mock=use_mock,
            configured_engine_id=configured_engine_id,
            allow_mock_fallback=allow_mock_fallback,
        )

        # Update project's NLP engine (for term extraction to use same engine)
        project = session.get(DictProject, project_id)
        if project:
            project.nlp_engine = engine.get_name()
            project.nlp_engine_version = engine.get_version()

        run = None
        run_id = batch_run_id
        if track_run:
            run = self._start_processor_run(
                session,
                project_id=project_id,
                engine=engine,
                runtime_status=runtime_status,
                doc_id=doc_id,
                use_gpu=use_gpu,
                use_mock=use_mock,
                is_reprocess=is_reprocess,
            )

            # Task 12: Save IDs before try block to avoid lazy-load after error
            run_id = run.run_id
        # doc_id already available as parameter

        try:
            # Update status
            doc.status = "processing"
            session.commit()

            # Get raw text
            doc_text = session.get(DocumentText, doc_id)
            if not doc_text or not doc_text.raw_text:
                raise ValueError("No text available for document")

            raw_text = doc_text.raw_text

            # Preprocess
            logger.debug("Preprocessing text...")
            cleaned_text = preprocess_text(raw_text)
            doc_text.cleaned_text = cleaned_text
            session.commit()

            # Split into sentences (simple splitting first)
            logger.debug("Splitting into sentences...")
            sentence_texts = split_into_sentences(cleaned_text)
            logger.info(f"Found {len(sentence_texts)} sentences")

            # Store sentences
            for sent_index, sent_text in enumerate(sentence_texts):
                sent = DocumentSentence(
                    doc_id=doc_id,
                    sent_index=sent_index,
                    text=sent_text,
                    corpus_id=doc.corpus_id,
                )
                session.add(sent)

            session.flush()

            # NLP processing
            logger.debug("Running NLP pipeline...")
            lemma_counter: Counter = Counter()
            lemma_pos_map: dict[str, str] = {}  # lemma_text -> most common POS
            lemma_sample_sentences: dict[str, int] = {}  # lemma_text -> sentence_id

            # Get all sentences back with IDs
            stmt = (
                select(DocumentSentence)
                .where(DocumentSentence.doc_id == doc_id)
                .order_by(DocumentSentence.sent_index)
            )
            sentences = session.execute(stmt).scalars().all()

            total_tokens = 0

            for sent_row in sentences:
                # Process sentence with NLP
                nlp_sentences = engine.process(sent_row.text)
                self._upsert_sentence_nlp_snapshot(
                    session,
                    sentence_row=sent_row,
                    engine=engine,
                    nlp_sentences=nlp_sentences,
                )

                if not nlp_sentences:
                    logger.warning(f"No NLP output for sentence {sent_row.sentence_id}")
                    continue

                # Typically one sentence, but could be split differently by Stanza
                for nlp_sent in nlp_sentences:
                    for token in nlp_sent.tokens:
                        total_tokens += 1

                        lemma_text = token.lemma.strip()
                        if not lemma_text:
                            continue

                        # Count lemma
                        lemma_counter[lemma_text] += 1

                        # Track most common POS for this lemma
                        if lemma_text not in lemma_pos_map:
                            lemma_pos_map[lemma_text] = token.pos

                        # Save first example sentence
                        if lemma_text not in lemma_sample_sentences:
                            lemma_sample_sentences[lemma_text] = sent_row.sentence_id

            logger.info(f"Processed {total_tokens} tokens, {len(lemma_counter)} unique lemmas")

            # Create or get lemmas
            lemma_id_map = self._create_or_get_lemmas(
                session,
                project_id,
                lemma_counter,
                lemma_pos_map,
            )

            # Calculate statistics
            self._update_lemma_statistics(
                session,
                project_id,
                doc_id,
                lemma_counter,
                lemma_id_map,
                lemma_sample_sentences,
            )

            # Update document status and metrics (Migration 003)
            doc.status = "processed"
            doc.processed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            doc.sentence_count = len(sentences)
            doc.token_count = total_tokens
            self.snapshot_doc_stats_service.set_document_valid(
                document=doc,
                snapshot_sentence_count=len(sentences),
            )
            session.commit()

            # Update run
            if run is not None:
                run.status = "ok"
                run.stage = "completed"
                run.finished_at = self._utc_now()
                run.last_doc_id = doc_id
                run.docs_processed = 1
                run.docs_failed = 0
                run.chunks_completed = 1
                run.tokens_total = total_tokens
                run.lemmas_total = len(lemma_counter)
                run.error_message = None
                session.commit()

            logger.info(f"Document {doc_id} processed successfully")
            return True

        except Exception as e:
            logger.exception(f"Failed to process document {doc_id}")

            # Task 12: Rollback immediately to clear PendingRollback state
            session.rollback()

            # Record error in a fresh transaction attempt
            try:
                error_msg = str(e)[:500]  # Truncate long error messages

                error = RunError(
                    run_id=run_id,  # Use saved ID, not lazy-loaded run.run_id
                    doc_id=doc_id,
                    stage="processing",
                    message=error_msg,
                )
                session.add(error)

                # Re-fetch objects in clean state
                run_obj = session.get(ProcessorRun, run_id) if run_id is not None else None
                if run is not None and run_obj:
                    run_obj.status = "failed"
                    run_obj.stage = "failed"
                    run_obj.finished_at = self._utc_now()
                    run_obj.last_doc_id = doc_id
                    run_obj.docs_failed = 1
                    run_obj.error_message = error_msg

                doc_obj = session.get(SourceDocument, doc_id)
                if doc_obj:
                    doc_obj.status = "failed"
                    doc_obj.error_message = error_msg

                session.commit()
            except Exception as inner_error:
                logger.error(f"Failed to record error for run {run_id}: {inner_error}")
                session.rollback()

            return False

    def _create_or_get_lemmas(
        self,
        session: Session,
        project_id: int,
        lemma_counter: Counter,
        lemma_pos_map: dict[str, str],
    ) -> dict[str, int]:
        """
        Create or get existing lemmas.

        Args:
            session: Database session
            project_id: Project ID
            lemma_counter: Counter of lemma frequencies
            lemma_pos_map: Mapping of lemma to POS

        Returns:
            Dictionary mapping lemma_text to lemma_id
        """
        lemma_id_map = {}
        stats = {"new": 0, "existing": 0, "noise": 0, "classes": Counter()}

        for lemma_text in lemma_counter:
            # Try to find existing lemma
            stmt = select(Lemma).where(
                Lemma.project_id == project_id,
                Lemma.lemma_text == lemma_text,
            )
            lemma = session.execute(stmt).scalar_one_or_none()

            if not lemma:
                # Classify the lemma (Task 11: Entity Classification)
                classification = classify_text(lemma_text)

                # Create new lemma with classification
                pos = lemma_pos_map.get(lemma_text, "X")
                lemma = Lemma(
                    project_id=project_id,
                    lemma_text=lemma_text,
                    pos=pos,
                    entity_class=classification.entity_class,
                    is_noise=1 if classification.is_noise else 0,
                    noise_reason=classification.noise_reason,
                    norm_text=classification.norm_text,
                    noise_source="auto",  # Epic 6A: initial classification is auto
                    noise_updated_at=datetime.now(UTC).isoformat(),
                )
                session.add(lemma)
                session.flush()

                stats["new"] += 1
                stats["classes"][classification.entity_class] += 1
                if classification.is_noise:
                    stats["noise"] += 1

                logger.debug(
                    f"Created lemma: {lemma_text} ({pos}) -> {classification.entity_class}"
                )
            else:
                stats["existing"] += 1

            lemma_id_map[lemma_text] = lemma.lemma_id

        # Log classification summary
        if stats["new"] > 0:
            logger.info(
                f"Created {stats['new']} new lemmas ({stats['noise']} noise, "
                f"{stats['new'] - stats['noise']} valid). "
                f"Classes: {dict(stats['classes'])}"
            )

        return lemma_id_map

    def _update_lemma_statistics(
        self,
        session: Session,
        project_id: int,
        doc_id: int,
        lemma_counter: Counter,
        lemma_id_map: dict[str, int],
        lemma_sample_sentences: dict[str, int],
    ) -> None:
        """
        Update lemma statistics (doc + project level).

        Args:
            session: Database session
            project_id: Project ID
            doc_id: Document ID
            lemma_counter: Counter of lemma frequencies
            lemma_id_map: Mapping of lemma_text to lemma_id
            lemma_sample_sentences: Sample sentences for each lemma
        """
        for lemma_text, freq in lemma_counter.items():
            lemma_id = lemma_id_map[lemma_text]
            sample_sent_id = lemma_sample_sentences.get(lemma_text)

            # Create doc-level stat
            doc_stat = LemmaDocStat(
                project_id=project_id,
                doc_id=doc_id,
                lemma_id=lemma_id,
                freq_abs=freq,
                sample_sentence_id=sample_sent_id,
            )
            session.add(doc_stat)

            # Update project-level stat
            stmt = select(LemmaProjectStat).where(
                LemmaProjectStat.project_id == project_id,
                LemmaProjectStat.lemma_id == lemma_id,
            )
            proj_stat = session.execute(stmt).scalar_one_or_none()

            if proj_stat:
                # Update existing
                proj_stat.freq_abs += freq
                proj_stat.doc_freq += 1
                proj_stat.updated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            else:
                # Create new
                proj_stat = LemmaProjectStat(
                    project_id=project_id,
                    lemma_id=lemma_id,
                    freq_abs=freq,
                    doc_freq=1,
                    sample_sentence_id=sample_sent_id,
                )
                session.add(proj_stat)

        session.flush()
        logger.debug(f"Updated statistics for {len(lemma_counter)} lemmas")

    @staticmethod
    def _chunk_int_ids(values: list[int], chunk_size: int = 500) -> list[list[int]]:
        ordered = [int(v) for v in values]
        size = max(1, int(chunk_size or 500))
        return [ordered[idx : idx + size] for idx in range(0, len(ordered), size)]

    def _get_document_lemma_ids(
        self,
        session: Session,
        *,
        project_id: int,
        doc_id: int,
    ) -> list[int]:
        rows = session.execute(
            text(
                "SELECT lemma_id FROM lemma_doc_stat "
                "WHERE project_id = :pid AND doc_id = :doc_id "
                "ORDER BY lemma_id"
            ),
            {"pid": int(project_id), "doc_id": int(doc_id)},
        ).fetchall()
        return [int(row[0]) for row in rows]

    def _cleanup_orphaned_lemmas_for_ids(
        self,
        session: Session,
        project_id: int,
        lemma_ids: list[int],
    ) -> int:
        """Delete lemma rows that became orphaned after removing one document's stats.

        Only lemma IDs referenced by the current document can become orphaned due to
        this operation. Restricting the cleanup to that candidate set avoids an
        expensive project-wide orphan sweep on large databases.
        """
        candidate_ids = sorted({int(lemma_id) for lemma_id in lemma_ids if lemma_id is not None})
        if not candidate_ids:
            return 0

        surviving_ids: set[int] = set()
        for chunk in self._chunk_int_ids(candidate_ids):
            param_names = [f"lemma_id_{idx}" for idx in range(len(chunk))]
            in_clause = ", ".join(f":{name}" for name in param_names)
            params = {"pid": int(project_id)}
            params.update(
                {name: int(lemma_id) for name, lemma_id in zip(param_names, chunk, strict=False)}
            )
            rows = session.execute(
                text(
                    "SELECT lemma_id FROM lemma_project_stat "
                    f"WHERE project_id = :pid AND lemma_id IN ({in_clause})"
                ),
                params,
            ).fetchall()
            surviving_ids.update(int(row[0]) for row in rows)

        orphan_ids = [lemma_id for lemma_id in candidate_ids if lemma_id not in surviving_ids]
        if not orphan_ids:
            return 0

        deleted = 0
        for chunk in self._chunk_int_ids(orphan_ids):
            param_names = [f"lemma_id_{idx}" for idx in range(len(chunk))]
            in_clause = ", ".join(f":{name}" for name in param_names)
            params = {"pid": int(project_id)}
            params.update(
                {name: int(lemma_id) for name, lemma_id in zip(param_names, chunk, strict=False)}
            )
            # Epic 6A: snapshot lemma_id → tm_entry.orphaned_lemma_id before deletion
            snap_params = {name: int(lid) for name, lid in zip(param_names, chunk, strict=False)}
            session.execute(
                text(
                    "UPDATE tm_entry SET orphaned_lemma_id = lemma_id "
                    f"WHERE lemma_id IN ({in_clause}) "
                    "AND orphaned_lemma_id IS NULL"
                ),
                snap_params,
            )
            session.execute(
                text("DELETE FROM lemma " f"WHERE project_id = :pid AND lemma_id IN ({in_clause})"),
                params,
            )
            deleted += len(chunk)

        logger.info(
            "Cleaned up %d orphaned lemmas from %d candidate lemma(s)",
            deleted,
            len(candidate_ids),
        )
        return deleted

    def _backfill_sentence_nlp_snapshots_for_document(
        self,
        session: Session,
        doc_id: int,
        *,
        engine: NLPEngine,
        batch_run_id: int | None = None,
    ) -> tuple[bool, str, int]:
        """Stage missing sentence snapshots for one already-processed document."""
        logger.info("Backfilling sentence snapshots for document %s...", doc_id)

        try:
            if batch_run_id is None:
                raise ValueError("batch_run_id is required for sentence snapshot staging")
            doc = session.get(SourceDocument, int(doc_id))
            if doc is None:
                raise ValueError(f"Document not found: {doc_id}")
            if str(doc.status or "") != "processed":
                return True, "Skipped non-processed document"

            stmt = (
                select(DocumentSentence, SentenceNLPSnapshot)
                .outerjoin(
                    SentenceNLPSnapshot,
                    SentenceNLPSnapshot.sentence_id == DocumentSentence.sentence_id,
                )
                .where(DocumentSentence.doc_id == int(doc_id))
                .order_by(DocumentSentence.sent_index.asc())
            )
            rows = session.execute(stmt).all()
            if not rows:
                return True, "No document_sentence rows to backfill", 0

            missing_count = 0
            token_total = 0
            stage_rows: list[dict[str, Any]] = []
            for sent_row, snapshot in rows:
                if snapshot is not None:
                    continue
                missing_count += 1
                nlp_sentences = engine.process(str(sent_row.text or ""))
                row = self._build_sentence_nlp_snapshot_values(
                    sentence_row=sent_row,
                    engine=engine,
                    nlp_sentences=nlp_sentences,
                )
                token_total += int(row["token_count"] or 0)
                stage_rows.append(row)

            if missing_count == 0:
                session.commit()
                return True, "Snapshots already present", 0

            self._stage_sentence_nlp_snapshot_rows(
                session,
                run_id=int(batch_run_id),
                rows=stage_rows,
            )
            session.commit()
            return (
                True,
                (f"Staged {missing_count} sentence snapshot(s)" f" ({token_total} token(s))"),
                missing_count,
            )
        except Exception as exc:
            logger.exception("Failed to backfill sentence snapshots for document %s", doc_id)
            session.rollback()
            try:
                self._record_batch_run_error(
                    session,
                    run_id=batch_run_id,
                    doc_id=doc_id,
                    stage="snapshot_backfill",
                    message=str(exc),
                )
                session.commit()
            except Exception:
                session.rollback()
            return False, str(exc), 0

    def backfill_sentence_snapshots_batch(
        self,
        session: Session,
        doc_ids: list[int],
        use_gpu: bool = False,
        use_mock: bool = False,
        configured_engine_id: str | None = None,
        allow_mock_fallback: bool = False,
        *,
        chunk_size: int = 50,
        chunk_sleep: float = 0.0,
        progress_callback: Callable[[int, int, str], None] | None = None,
        state_callback: Callable[[dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        pause_check: Callable[[], bool] | None = None,
        resume_latest: bool = False,
        resume_run_id: int | None = None,
        source_label: str = "snapshot_backfill",
        integrity_checkpoint_mode: str = "none",
        merge_batch_size: int = 1000,
        segment_quick_check_timeout: float = 0.5,
    ) -> tuple[int, int]:
        """Backfill missing sentence snapshots for a deterministic processed-doc slice.

        Storage-level durability is handled through:
        - per-document staging into `sentence_nlp_snapshot_stage`
        - bounded merge batches into `sentence_nlp_snapshot`
        - super-chunk integrity checks before advancing resumable run state
        """
        if resume_latest and resume_run_id is not None:
            raise ValueError("resume_latest and resume_run_id are mutually exclusive")

        ordered_ids = sorted({int(doc_id) for doc_id in doc_ids})
        if not ordered_ids:
            return 0, 0
        if chunk_size <= 0:
            raise ValueError("chunk_size must be >= 1")
        if merge_batch_size <= 0:
            raise ValueError("merge_batch_size must be >= 1")
        if segment_quick_check_timeout < 0:
            raise ValueError("segment_quick_check_timeout must be >= 0")

        project_id = self._resolve_project_id_for_docs(session, ordered_ids)
        engine, runtime_status = self._resolve_nlp_runtime(
            use_gpu=use_gpu,
            use_mock=use_mock,
            configured_engine_id=configured_engine_id,
            allow_mock_fallback=allow_mock_fallback,
        )
        params_hash = self._build_run_params_hash(
            engine=engine,
            configured_engine_id=runtime_status.configured_engine_id,
            effective_engine_id=runtime_status.effective_engine_id or engine.get_name(),
            use_gpu=use_gpu,
            use_mock=use_mock,
            fallback_used=runtime_status.fallback_used,
            is_reprocess=False,
            contract="snapshot_backfill_v1",
        )
        total_chunks = math.ceil(len(ordered_ids) / chunk_size)
        effective_chunk_size = int(chunk_size)
        bounded_validation = len(ordered_ids) >= SNAPSHOT_BOUNDED_VALIDATION_MIN_DOCS

        run = None
        verification: dict[str, Any] | None = None
        if resume_run_id is not None:
            verification = self.verify_batch_run_contract(
                session,
                ordered_ids,
                use_gpu=use_gpu,
                use_mock=use_mock,
                configured_engine_id=configured_engine_id,
                allow_mock_fallback=allow_mock_fallback,
                source_label=source_label,
                resume_run_id=resume_run_id,
                contract="snapshot_backfill_v1",
            )
            if not verification.get("ok"):
                raise ValueError(
                    str(verification.get("reason") or "Explicit snapshot backfill resume failed")
                )
            run = session.get(ProcessorRun, int(verification["run_id"]))
        elif resume_latest:
            verification = self.verify_batch_run_contract(
                session,
                ordered_ids,
                use_gpu=use_gpu,
                use_mock=use_mock,
                configured_engine_id=configured_engine_id,
                allow_mock_fallback=allow_mock_fallback,
                source_label=source_label,
                resume_latest=True,
                contract="snapshot_backfill_v1",
            )
            if verification.get("ok"):
                run = session.get(ProcessorRun, int(verification["run_id"]))

        if run is None:
            run = ProcessorRun(
                project_id=project_id,
                engine=engine.get_name(),
                engine_version=engine.get_version(),
                docs_total=len(ordered_ids),
                docs_processed=0,
                docs_failed=0,
                chunks_total=total_chunks,
                chunks_completed=0,
                status="running",
                stage="snapshot_backfill",
                params_hash=params_hash,
                note=self._build_batch_run_note(
                    doc_ids=ordered_ids,
                    chunk_size=chunk_size,
                    source_label=source_label,
                    is_reprocess=False,
                    extra_note={
                        "contract": "snapshot_backfill_v1",
                        "runtime": self._build_runtime_provenance_payload(
                            runtime_status=runtime_status,
                            use_gpu=use_gpu,
                            use_mock=use_mock,
                            is_reprocess=False,
                            source_label=source_label,
                            kind="batch_nlp",
                        ),
                        "validation_scope": "bounded" if bounded_validation else "limited",
                        "validated_doc_count": len(ordered_ids) if bounded_validation else 0,
                        "selected_doc_count": len(ordered_ids),
                    },
                ),
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            self._emit_run_state(
                state_callback,
                run,
                phase="started",
                message="Created sentence snapshot backfill run",
            )
        else:
            if verification and verification.get("chunk_size"):
                effective_chunk_size = max(1, int(verification["chunk_size"]))
            run.status = "running"
            run.stage = "snapshot_backfill"
            run.error_message = None
            run.finished_at = None
            session.commit()
            session.refresh(run)
            self._emit_run_state(
                state_callback,
                run,
                phase="resumed",
                message=(
                    "Resuming selected sentence snapshot backfill run"
                    if resume_run_id is not None
                    else "Resuming latest incomplete sentence snapshot backfill run"
                ),
            )

        discarded_stage_rows = self._clear_sentence_nlp_snapshot_stage(
            session,
            run_id=int(run.run_id),
        )
        if discarded_stage_rows > 0:
            session.commit()
            session.refresh(run)
            self._emit_run_state(
                state_callback,
                run,
                phase="staging_reset",
                message=(
                    "Discarded "
                    f"{discarded_stage_rows} stale staged sentence snapshot row(s) before continuing"
                ),
            )

        remaining_ids = [
            doc_id
            for doc_id in ordered_ids
            if run.last_doc_id is None or int(doc_id) > int(run.last_doc_id)
        ]
        if not remaining_ids:
            self._clear_sentence_nlp_snapshot_stage(session, run_id=int(run.run_id))
            session.commit()
            return self._finalize_snapshot_backfill_run(
                session,
                run=run,
                success=0,
                errors=int(run.docs_failed or 0),
                integrity_checkpoint_mode=integrity_checkpoint_mode,
                state_callback=state_callback,
                completion_message="No remaining documents for this sentence snapshot backfill run",
            )

        success = 0
        errors = 0
        current_chunk_doc_ids: list[int] = []
        current_chunk_success = 0
        current_chunk_errors = 0
        current_chunk_stage_rows = 0

        def _fail_current_run(message: str, *, stage: str) -> None:
            try:
                self._clear_sentence_nlp_snapshot_stage(session, run_id=int(run.run_id))
                self._record_batch_run_error(
                    session,
                    run_id=int(run.run_id),
                    doc_id=int(current_chunk_doc_ids[-1]) if current_chunk_doc_ids else None,
                    stage=stage,
                    message=message,
                )
                run.status = "failed"
                run.stage = "failed_integrity"
                run.finished_at = self._utc_now()
                run.error_message = str(message)[:500]
                session.commit()
                session.refresh(run)
            except Exception:
                session.rollback()
                logger.exception(
                    "Failed to persist failure state for sentence snapshot backfill run %s",
                    int(run.run_id),
                )
            self._emit_run_state(
                state_callback,
                run,
                phase="failed",
                message=message,
            )
            raise RuntimeError(message)

        def _merge_current_chunk() -> None:
            nonlocal success
            nonlocal errors
            nonlocal current_chunk_doc_ids
            nonlocal current_chunk_success
            nonlocal current_chunk_errors
            nonlocal current_chunk_stage_rows

            if not current_chunk_doc_ids:
                return

            chunk_no = int(run.chunks_completed or 0) + 1
            run.stage = "snapshot_backfill_merge"
            session.commit()
            session.refresh(run)
            self._emit_run_state(
                state_callback,
                run,
                phase="merging_chunk",
                message=(
                    "Merging staged sentence snapshot chunk "
                    f"{chunk_no}/{int(run.chunks_total or 0)} "
                    f"({current_chunk_stage_rows} staged row(s))"
                ),
            )

            try:
                with self.db_service.get_session() as merge_session:
                    if current_chunk_stage_rows > 0:
                        self.snapshot_doc_stats_service.mark_documents_unknown(
                            merge_session,
                            current_chunk_doc_ids,
                        )
                        merge_session.commit()
                    merged_rows = self._merge_sentence_nlp_snapshot_stage(
                        merge_session,
                        run_id=int(run.run_id),
                        merge_batch_size=int(merge_batch_size),
                    )
                    if current_chunk_stage_rows > 0:
                        self.snapshot_doc_stats_service.refresh_document_stats(
                            merge_session,
                            current_chunk_doc_ids,
                        )
                        merge_session.commit()
            except Exception as exc:
                logger.exception(
                    "Failed to merge staged sentence snapshot chunk for run %s",
                    int(run.run_id),
                )
                _fail_current_run(
                    f"Failed to merge staged sentence snapshot chunk: {str(exc)[:350]}",
                    stage="snapshot_backfill_merge",
                )
                return

            run.stage = "segment_integrity_check"
            session.commit()
            session.refresh(run)
            self._emit_run_state(
                state_callback,
                run,
                phase="verifying_chunk_integrity",
                message=(
                    "Running bounded physical verification after staged chunk "
                    f"{chunk_no}/{int(run.chunks_total or 0)}"
                ),
            )
            segment_integrity = self._run_snapshot_backfill_segment_check(
                quick_check_timeout_sec=float(segment_quick_check_timeout),
            )
            if not segment_integrity.get("ok"):
                _fail_current_run(
                    str(
                        segment_integrity.get("error")
                        or "Sentence snapshot chunk integrity verification failed"
                    )[:500],
                    stage="segment_integrity_check",
                )
                return

            success += current_chunk_success
            errors += current_chunk_errors
            run.docs_processed = int(run.docs_processed or 0) + current_chunk_success
            run.docs_failed = int(run.docs_failed or 0) + current_chunk_errors
            run.last_doc_id = int(current_chunk_doc_ids[-1])
            run.chunks_completed = int(run.chunks_completed or 0) + 1
            run.stage = "snapshot_backfill"
            session.commit()
            session.refresh(run)

            chunk_message = (
                "Completed staged sentence snapshot chunk "
                f"{int(run.chunks_completed or 0)}/{int(run.chunks_total or 0)} "
                f"({merged_rows} merged row(s))"
            )
            if segment_integrity.get("quick_check_timed_out"):
                chunk_message += "; bounded quick_check timed out"
            self._emit_run_state(
                state_callback,
                run,
                phase="chunk_complete",
                message=chunk_message,
            )

            current_chunk_doc_ids = []
            current_chunk_success = 0
            current_chunk_errors = 0
            current_chunk_stage_rows = 0

            docs_done = int(run.docs_processed or 0) + int(run.docs_failed or 0)
            if chunk_sleep > 0 and docs_done < int(run.docs_total or 0):
                time.sleep(chunk_sleep)

        def _cancel_current_run(message: str) -> tuple[int, int]:
            staged_rows = self._clear_sentence_nlp_snapshot_stage(
                session,
                run_id=int(run.run_id),
            )
            run.status = "cancelled"
            run.stage = "cancelled"
            run.finished_at = self._utc_now()
            session.commit()
            session.refresh(run)
            final_message = message
            if staged_rows > 0:
                final_message += f"; discarded {staged_rows} unmerged staged row(s)"
            self._emit_run_state(state_callback, run, phase="cancelled", message=final_message)
            return success, errors

        for doc_id in remaining_ids:
            if cancel_check and cancel_check():
                return _cancel_current_run("Cancellation requested before next document")

            if pause_check and pause_check():
                run.status = "paused"
                run.stage = "paused"
                session.commit()
                session.refresh(run)
                self._emit_run_state(
                    state_callback,
                    run,
                    phase="paused",
                    message="Paused at sentence snapshot backfill checkpoint",
                )
                while pause_check and pause_check():
                    if cancel_check and cancel_check():
                        return _cancel_current_run(
                            "Cancellation requested while paused at sentence snapshot backfill checkpoint"
                        )
                    time.sleep(0.1)
                run.status = "running"
                run.stage = "snapshot_backfill"
                session.commit()
                session.refresh(run)
                self._emit_run_state(
                    state_callback,
                    run,
                    phase="resumed",
                    message="Resumed sentence snapshot backfill run",
                )

            with self.db_service.get_session() as doc_session:
                doc = doc_session.get(SourceDocument, int(doc_id))
                doc_name = doc.file_name if doc else f"Doc {doc_id}"
                done_before = (
                    int(run.docs_processed or 0)
                    + int(run.docs_failed or 0)
                    + current_chunk_success
                    + current_chunk_errors
                )
                if progress_callback:
                    progress_callback(done_before + 1, int(run.docs_total or 0), doc_name)
                if cancel_check and cancel_check():
                    return _cancel_current_run(
                        "Cancellation requested after progress update at sentence snapshot backfill checkpoint"
                    )
                if pause_check and pause_check():
                    run.status = "paused"
                    run.stage = "paused"
                    session.commit()
                    session.refresh(run)
                    self._emit_run_state(
                        state_callback,
                        run,
                        phase="paused",
                        message="Paused at sentence snapshot backfill checkpoint",
                    )
                    while pause_check and pause_check():
                        if cancel_check and cancel_check():
                            return _cancel_current_run(
                                "Cancellation requested while paused at sentence snapshot backfill checkpoint"
                            )
                        time.sleep(0.1)
                    run.status = "running"
                    run.stage = "snapshot_backfill"
                    session.commit()
                    session.refresh(run)
                    self._emit_run_state(
                        state_callback,
                        run,
                        phase="resumed",
                        message="Resumed sentence snapshot backfill run",
                    )
                ok, detail, staged_rows = self._backfill_sentence_nlp_snapshots_for_document(
                    doc_session,
                    int(doc_id),
                    engine=engine,
                    batch_run_id=int(run.run_id),
                )

            current_chunk_doc_ids.append(int(doc_id))
            current_chunk_stage_rows += int(staged_rows or 0)
            if ok:
                current_chunk_success += 1
            else:
                current_chunk_errors += 1

            self._emit_run_state(
                state_callback,
                run,
                phase="processing",
                message=detail,
                doc_name=doc_name,
            )

            if len(current_chunk_doc_ids) >= effective_chunk_size:
                _merge_current_chunk()

        if current_chunk_doc_ids:
            _merge_current_chunk()

        self._clear_sentence_nlp_snapshot_stage(session, run_id=int(run.run_id))
        session.commit()
        return self._finalize_snapshot_backfill_run(
            session,
            run=run,
            success=success,
            errors=errors,
            integrity_checkpoint_mode=integrity_checkpoint_mode,
            state_callback=state_callback,
            completion_message="Sentence snapshot backfill run completed",
        )

    def process_documents_batch(
        self,
        session: Session,
        doc_ids: list[int],
        use_gpu: bool = False,
        use_mock: bool = False,
        configured_engine_id: str | None = None,
        allow_mock_fallback: bool = False,
        *,
        is_reprocess: bool = False,
        chunk_size: int = 50,
        chunk_sleep: float = 0.0,
        progress_callback: Callable[[int, int, str], None] | None = None,
        state_callback: Callable[[dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        pause_check: Callable[[], bool] | None = None,
        resume_latest: bool = False,
        resume_run_id: int | None = None,
        source_label: str = "batch",
    ) -> tuple[int, int]:
        """
        Process multiple documents through a batch-level resumable run.

        Args:
            session: Database session
            doc_ids: List of document IDs
            use_gpu: Whether to use GPU
            use_mock: Use mock engine instead of Stanza
            is_reprocess: Whether this is a re-processing batch
            chunk_size: Chunk size used for progress accounting and pause/cancel checkpoints
            chunk_sleep: Optional sleep in seconds after each completed chunk
            progress_callback: Optional callback(current, total, doc_name)
            state_callback: Optional structured state callback(dict payload)
            cancel_check: Optional cooperative cancel callback
            pause_check: Optional cooperative pause callback
            resume_latest: Resume latest matching incomplete batch run if possible
            resume_run_id: Resume this exact incomplete batch run if possible
            source_label: Batch source identifier for run-note routing

        Returns:
            Tuple of (success_count, error_count)
        """
        if resume_latest and resume_run_id is not None:
            raise ValueError("resume_latest and resume_run_id are mutually exclusive")

        ordered_ids = sorted({int(doc_id) for doc_id in doc_ids})
        if not ordered_ids:
            return 0, 0
        if chunk_size <= 0:
            raise ValueError("chunk_size must be >= 1")

        project_id = self._resolve_project_id_for_docs(session, ordered_ids)
        engine, runtime_status = self._resolve_nlp_runtime(
            use_gpu=use_gpu,
            use_mock=use_mock,
            configured_engine_id=configured_engine_id,
            allow_mock_fallback=allow_mock_fallback,
        )
        params_hash = self._build_run_params_hash(
            engine=engine,
            configured_engine_id=runtime_status.configured_engine_id,
            effective_engine_id=runtime_status.effective_engine_id or engine.get_name(),
            use_gpu=use_gpu,
            use_mock=use_mock,
            fallback_used=runtime_status.fallback_used,
            is_reprocess=is_reprocess,
        )
        total_chunks = math.ceil(len(ordered_ids) / chunk_size)
        effective_chunk_size = int(chunk_size)
        run_note: dict[str, Any] = {}

        run = None
        verification: dict[str, Any] | None = None
        if resume_run_id is not None:
            verification = self.verify_batch_run_contract(
                session,
                ordered_ids,
                use_gpu=use_gpu,
                use_mock=use_mock,
                configured_engine_id=configured_engine_id,
                allow_mock_fallback=allow_mock_fallback,
                is_reprocess=is_reprocess,
                source_label=source_label,
                resume_run_id=resume_run_id,
            )
            if not verification.get("ok"):
                raise ValueError(str(verification.get("reason") or "Explicit batch resume failed"))
            run = session.get(ProcessorRun, int(verification["run_id"]))
        elif resume_latest:
            verification = self.verify_batch_run_contract(
                session,
                ordered_ids,
                use_gpu=use_gpu,
                use_mock=use_mock,
                configured_engine_id=configured_engine_id,
                allow_mock_fallback=allow_mock_fallback,
                is_reprocess=is_reprocess,
                source_label=source_label,
                resume_latest=True,
            )
            if verification.get("ok"):
                run = session.get(ProcessorRun, int(verification["run_id"]))

        if run is None:
            run = ProcessorRun(
                project_id=project_id,
                engine=engine.get_name(),
                engine_version=engine.get_version(),
                docs_total=len(ordered_ids),
                docs_processed=0,
                docs_failed=0,
                chunks_total=total_chunks,
                chunks_completed=0,
                status="running",
                stage="queued",
                params_hash=params_hash,
                note=self._build_batch_run_note(
                    doc_ids=ordered_ids,
                    chunk_size=chunk_size,
                    source_label=source_label,
                    is_reprocess=is_reprocess,
                    extra_note={
                        "runtime": self._build_runtime_provenance_payload(
                            runtime_status=runtime_status,
                            use_gpu=use_gpu,
                            use_mock=use_mock,
                            is_reprocess=is_reprocess,
                            source_label=source_label,
                            kind="batch_nlp",
                        ),
                    },
                ),
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            run_note = self._parse_batch_run_note(run.note)
            self._emit_run_state(
                state_callback,
                run,
                phase="started",
                message="Created NLP batch run",
            )
        else:
            run_note = self._parse_batch_run_note(run.note)
            if verification and verification.get("chunk_size"):
                effective_chunk_size = max(1, int(verification["chunk_size"]))
            else:
                effective_chunk_size = max(1, int(run_note.get("chunk_size") or chunk_size))
            run.status = "running"
            run.stage = "resuming"
            run.error_message = None
            run.finished_at = None
            session.commit()
            session.refresh(run)
            self._emit_run_state(
                state_callback,
                run,
                phase="resumed",
                message=(
                    "Resuming selected NLP batch run"
                    if resume_run_id is not None
                    else "Resuming latest incomplete NLP batch run"
                ),
            )

        remaining_ids = [
            doc_id
            for doc_id in ordered_ids
            if run.last_doc_id is None or int(doc_id) > int(run.last_doc_id)
        ]
        if not remaining_ids:
            run.status = "ok"
            run.stage = "completed_with_errors" if int(run.docs_failed or 0) > 0 else "completed"
            run.finished_at = self._utc_now()
            if int(run.docs_failed or 0) > 0:
                run.error_message = (
                    f"{int(run.docs_failed)} document(s) failed during batch processing"
                )
            session.commit()
            session.refresh(run)
            self._emit_run_state(
                state_callback,
                run,
                phase="completed",
                message="No remaining documents for this batch run",
            )
            return 0, 0

        success = 0
        errors = 0

        def _cancel_current_run(message: str) -> tuple[int, int]:
            run.status = "cancelled"
            run.stage = "cancelled"
            run.finished_at = self._utc_now()
            session.commit()
            session.refresh(run)
            self._emit_run_state(state_callback, run, phase="cancelled", message=message)
            return success, errors

        for doc_id in remaining_ids:
            if cancel_check and cancel_check():
                return _cancel_current_run("Cancellation requested before next document")

            if pause_check and pause_check():
                run.status = "paused"
                run.stage = "paused"
                session.commit()
                session.refresh(run)
                self._emit_run_state(
                    state_callback,
                    run,
                    phase="paused",
                    message="Paused at document checkpoint",
                )
                while pause_check and pause_check():
                    if cancel_check and cancel_check():
                        return _cancel_current_run(
                            "Cancellation requested while paused at checkpoint"
                        )
                    time.sleep(0.1)
                run.status = "running"
                run.stage = "processing"
                session.commit()
                session.refresh(run)
                self._emit_run_state(
                    state_callback,
                    run,
                    phase="resumed",
                    message="Resumed NLP batch run",
                )

            with self.db_service.get_session() as doc_session:
                doc = doc_session.get(SourceDocument, doc_id)
                doc_name = doc.file_name if doc else f"Doc {doc_id}"
                done_before = int(run.docs_processed or 0) + int(run.docs_failed or 0)
                if progress_callback:
                    progress_callback(done_before + 1, int(run.docs_total or 0), doc_name)
                if cancel_check and cancel_check():
                    return _cancel_current_run(
                        "Cancellation requested after progress update at document checkpoint"
                    )
                if pause_check and pause_check():
                    run.status = "paused"
                    run.stage = "paused"
                    session.commit()
                    session.refresh(run)
                    self._emit_run_state(
                        state_callback,
                        run,
                        phase="paused",
                        message="Paused at document checkpoint",
                    )
                    while pause_check and pause_check():
                        if cancel_check and cancel_check():
                            return _cancel_current_run(
                                "Cancellation requested while paused at checkpoint"
                            )
                        time.sleep(0.1)
                    run.status = "running"
                    run.stage = "processing"
                    session.commit()
                    session.refresh(run)
                    self._emit_run_state(
                        state_callback,
                        run,
                        phase="resumed",
                        message="Resumed NLP batch run",
                    )
                if is_reprocess:
                    ok = self.reprocess_document(
                        doc_session,
                        doc_id,
                        use_gpu=use_gpu,
                        use_mock=use_mock,
                        configured_engine_id=configured_engine_id,
                        allow_mock_fallback=allow_mock_fallback,
                        track_run=False,
                        batch_run_id=int(run.run_id),
                    )
                else:
                    ok = self.process_document(
                        doc_session,
                        doc_id,
                        use_gpu=use_gpu,
                        use_mock=use_mock,
                        configured_engine_id=configured_engine_id,
                        allow_mock_fallback=allow_mock_fallback,
                        is_reprocess=is_reprocess,
                        track_run=False,
                        batch_run_id=int(run.run_id),
                    )

            if ok:
                success += 1
                run.docs_processed = int(run.docs_processed or 0) + 1
            else:
                errors += 1
                run.docs_failed = int(run.docs_failed or 0) + 1

            docs_done = int(run.docs_processed or 0) + int(run.docs_failed or 0)
            run.last_doc_id = int(doc_id)
            run.chunks_completed = docs_done // effective_chunk_size
            run.stage = "processing"
            session.commit()
            session.refresh(run)
            self._emit_run_state(
                state_callback,
                run,
                phase="processing",
                message=f"Processed {doc_name}",
                doc_name=doc_name,
            )

            if docs_done % effective_chunk_size == 0:
                self._emit_run_state(
                    state_callback,
                    run,
                    phase="chunk_complete",
                    message=(
                        f"Completed chunk {int(run.chunks_completed or 0)}/"
                        f"{int(run.chunks_total or 0)}"
                    ),
                )
                if chunk_sleep > 0 and docs_done < int(run.docs_total or 0):
                    time.sleep(chunk_sleep)

        run.status = "ok"
        run.stage = "completed_with_errors" if errors > 0 else "completed"
        run.finished_at = self._utc_now()
        run.chunks_completed = int(run.chunks_total or 0)
        run.error_message = (
            f"{errors} document(s) failed during batch processing" if errors > 0 else None
        )
        session.commit()
        session.refresh(run)
        self._emit_run_state(
            state_callback,
            run,
            phase="completed",
            message="NLP batch run completed",
        )

        logger.info(
            "Batch processing complete: %d succeeded, %d failed (run_id=%d)",
            success,
            errors,
            int(run.run_id),
        )
        return success, errors

    # ========================================================================
    # M4: Live Update - Delta Statistics
    # ========================================================================

    def remove_document_stats(self, session: Session, doc_id: int) -> bool:
        """
        Remove document statistics using delta subtraction.

        This is called before deleting a document to maintain accurate
        project-level statistics.

        Args:
            session: Database session
            doc_id: Document ID to remove stats for

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get document to find project_id
            doc = session.get(SourceDocument, doc_id)
            if not doc:
                logger.warning(f"Document {doc_id} not found")
                return False

            # Get corpus to find project_id
            from app.infra.sa_models import SourceCorpus

            corpus = session.get(SourceCorpus, doc.corpus_id)
            if not corpus:
                logger.warning(f"Corpus {doc.corpus_id} not found")
                return False

            project_id = corpus.project_id

            logger.info(f"Removing statistics for document {doc_id} (project {project_id})")

            doc_lemma_ids = self._get_document_lemma_ids(
                session,
                project_id=int(project_id),
                doc_id=int(doc_id),
            )
            doc_stats_count = len(doc_lemma_ids)
            if doc_stats_count <= 0:
                logger.info("No statistics to remove")
                return True

            updated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            params = {
                "pid": int(project_id),
                "doc_id": int(doc_id),
                "updated_at": updated_at,
            }
            session.execute(
                text(
                    "UPDATE lemma_project_stat "
                    "SET freq_abs = freq_abs - ("
                    "  SELECT lds.freq_abs FROM lemma_doc_stat lds "
                    "  WHERE lds.project_id = :pid "
                    "    AND lds.doc_id = :doc_id "
                    "    AND lds.lemma_id = lemma_project_stat.lemma_id"
                    "), "
                    "doc_freq = doc_freq - 1, "
                    "updated_at = :updated_at "
                    "WHERE project_id = :pid "
                    "AND EXISTS ("
                    "  SELECT 1 FROM lemma_doc_stat lds "
                    "  WHERE lds.project_id = :pid "
                    "    AND lds.doc_id = :doc_id "
                    "    AND lds.lemma_id = lemma_project_stat.lemma_id"
                    ")"
                ),
                params,
            )
            session.execute(
                text("DELETE FROM lemma_doc_stat " "WHERE project_id = :pid AND doc_id = :doc_id"),
                params,
            )
            session.execute(
                text(
                    "DELETE FROM lemma_project_stat "
                    "WHERE project_id = :pid AND (freq_abs <= 0 OR doc_freq <= 0)"
                ),
                params,
            )

            # Only lemma IDs touched by this document can become orphaned here.
            self._cleanup_orphaned_lemmas_for_ids(session, int(project_id), doc_lemma_ids)

            logger.info(f"Removed statistics for {doc_stats_count} lemmas")
            return True

        except Exception:
            logger.exception(f"Failed to remove document stats for {doc_id}")
            try:
                session.rollback()
            except Exception:
                logger.debug(
                    "Rollback after remove_document_stats failure also failed", exc_info=True
                )
            return False

    def _cleanup_orphaned_lemmas(self, session: Session, project_id: int) -> int:
        """
        Delete lemmas that no longer have any project statistics.

        Args:
            session: Database session
            project_id: Project ID

        Returns:
            Number of lemmas deleted
        """
        orphan_count = int(
            session.execute(
                text(
                    "SELECT COUNT(*) FROM lemma l "
                    "WHERE l.project_id = :pid "
                    "AND NOT EXISTS ("
                    "  SELECT 1 FROM lemma_project_stat lps "
                    "  WHERE lps.project_id = :pid AND lps.lemma_id = l.lemma_id"
                    ")"
                ),
                {"pid": int(project_id)},
            ).scalar()
            or 0
        )
        if orphan_count <= 0:
            return 0

        session.execute(
            text(
                "DELETE FROM lemma "
                "WHERE project_id = :pid "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM lemma_project_stat lps "
                "  WHERE lps.project_id = :pid AND lps.lemma_id = lemma.lemma_id"
                ")"
            ),
            {"pid": int(project_id)},
        )
        logger.info(f"Cleaned up {orphan_count} orphaned lemmas")
        return orphan_count

    def _clear_document_sentences_fast(self, session: Session, doc_id: int) -> int:
        """Delete old sentences for reprocess without ORM row-by-row deletes."""
        sentence_count = int(
            session.execute(
                text("SELECT COUNT(*) FROM document_sentence WHERE doc_id = :doc_id"),
                {"doc_id": int(doc_id)},
            ).scalar()
            or 0
        )
        if sentence_count <= 0:
            return 0

        params = {"doc_id": int(doc_id)}
        sentence_ids_sql = "SELECT sentence_id FROM document_sentence WHERE doc_id = :doc_id"

        # Clear surviving sentence references once before deleting sentence rows.
        session.execute(
            text(
                "UPDATE lemma_project_stat SET sample_sentence_id = NULL "
                f"WHERE sample_sentence_id IN ({sentence_ids_sql})"
            ),
            params,
        )
        session.execute(
            text(
                "UPDATE ngram_doc_stat SET sample_sentence_id = NULL "
                f"WHERE sample_sentence_id IN ({sentence_ids_sql})"
            ),
            params,
        )
        session.execute(
            text(
                "UPDATE ngram_project_stat SET sample_sentence_id = NULL "
                f"WHERE sample_sentence_id IN ({sentence_ids_sql})"
            ),
            params,
        )
        session.execute(
            text(
                "UPDATE term_card SET pinned_sentence_id = NULL "
                f"WHERE pinned_sentence_id IN ({sentence_ids_sql})"
            ),
            params,
        )
        session.execute(
            text(
                "UPDATE term_cluster SET pinned_example_sent_id = NULL "
                f"WHERE pinned_example_sent_id IN ({sentence_ids_sql})"
            ),
            params,
        )
        session.execute(
            text(
                f"DELETE FROM sentence_pronunciation " f"WHERE sentence_id IN ({sentence_ids_sql})"
            ),
            params,
        )
        session.execute(
            text("DELETE FROM document_sentence WHERE doc_id = :doc_id"),
            params,
        )
        logger.info("Deleted %d old sentences for doc %d", sentence_count, int(doc_id))
        return sentence_count

    def reprocess_document(
        self,
        session: Session,
        doc_id: int,
        use_gpu: bool = False,
        use_mock: bool = False,
        configured_engine_id: str | None = None,
        allow_mock_fallback: bool = False,
        track_run: bool = True,
        batch_run_id: int | None = None,
    ) -> bool:
        """
        Re-process a document with automatic delta statistics update.

        Steps:
        1. Check document exists and is processed
        2. Set status to 'processing'
        3. Remove old statistics (delta subtraction)
        4. Delete old sentences
        5. Run NLP processing again
        6. Set status to 'processed'

        Args:
            session: Database session
            doc_id: Document ID to reprocess
            use_gpu: Whether to use GPU
            use_mock: Use mock engine instead of Stanza
            track_run: Whether to create/update a dedicated per-document run row
            batch_run_id: Optional batch-level run ID for shared error logging

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get document
            doc = session.get(SourceDocument, doc_id)
            if not doc:
                logger.error(f"Document {doc_id} not found")
                return False

            if doc.status not in ("processed", "failed"):
                logger.warning(f"Document {doc_id} is not processed (status: {doc.status})")
                # Allow reprocessing anyway (for failed docs)

            logger.info(f"Re-processing document {doc_id}: {doc.file_name}")

            # Step 1: Set status to 'processing'
            doc.status = "processing"
            session.flush()

            # Step 2: Remove old statistics
            if not self.remove_document_stats(session, doc_id):
                logger.error(f"Failed to remove old stats for document {doc_id}")
                session.rollback()
                doc = session.get(SourceDocument, int(doc_id))
                doc.status = "failed"
                doc.error_message = "Failed to remove old statistics"
                session.commit()
                return False

            # Step 3: Delete old sentences
            deleted_sentences = self._clear_document_sentences_fast(session, doc_id)
            logger.info(f"Deleted {deleted_sentences} old sentences")

            # Step 4: Run NLP processing
            # Note: process_document will handle the rest
            # We need to temporarily reset status to 'imported' so process_document works
            doc.status = "imported"
            doc.processed_at = None
            doc.snapshot_sentence_count = 0
            doc.snapshot_stats_state = "unknown"
            doc.snapshot_stats_updated_at = self._utc_now()
            session.flush()

            # Process
            process_kwargs = {
                "use_gpu": use_gpu,
                "use_mock": use_mock,
                "configured_engine_id": configured_engine_id,
                "allow_mock_fallback": allow_mock_fallback,
            }
            if "is_reprocess" in inspect.signature(self.process_document).parameters:
                process_kwargs["is_reprocess"] = True
            if "track_run" in inspect.signature(self.process_document).parameters:
                process_kwargs["track_run"] = track_run
            if "batch_run_id" in inspect.signature(self.process_document).parameters:
                process_kwargs["batch_run_id"] = batch_run_id

            success = self.process_document(session, doc_id, **process_kwargs)

            if success:
                logger.info(f"Document {doc_id} re-processed successfully")
            else:
                logger.error(f"Failed to re-process document {doc_id}")

            return success

        except Exception as e:
            logger.exception(f"Failed to reprocess document {doc_id}")
            try:
                session.rollback()
            except Exception:
                logger.debug("Rollback after reprocess failure also failed", exc_info=True)
            # Set status to failed
            doc = session.get(SourceDocument, doc_id)
            if doc:
                doc.status = "failed"
                doc.error_message = f"Re-processing error: {str(e)}"
                session.commit()
            return False

    def bulk_reprocess(
        self,
        session: Session,
        doc_ids: list[int],
        use_gpu: bool = False,
        use_mock: bool = False,
        configured_engine_id: str | None = None,
        allow_mock_fallback: bool = False,
    ) -> tuple[int, int]:
        """
        Re-process multiple documents with delta statistics.

        Args:
            session: Database session
            doc_ids: List of document IDs
            use_gpu: Whether to use GPU
            use_mock: Use mock engine

        Returns:
            Tuple of (success_count, error_count)
        """
        success = 0
        errors = 0

        logger.info(f"Bulk re-processing {len(doc_ids)} documents")

        for doc_id in doc_ids:
            if self.reprocess_document(
                session,
                doc_id,
                use_gpu=use_gpu,
                use_mock=use_mock,
                configured_engine_id=configured_engine_id,
                allow_mock_fallback=allow_mock_fallback,
            ):
                success += 1
            else:
                errors += 1

        logger.info(f"Bulk re-processing complete: {success} succeeded, {errors} failed")
        return success, errors
