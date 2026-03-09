"""Document processing service."""
from dataclasses import asdict
import inspect
import logging
import json
import hashlib
import math
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import select, text, update

from app.infra.sa_models import (
    SourceDocument,
    DocumentText,
    DocumentSentence,
    SentenceNLPSnapshot,
    Lemma,
    LemmaDocStat,
    LemmaProjectStat,
    ProcessorRun,
    RunError,
    DictProject,
)
from app.domain.dto import NLPProcessRunState
from app.infra.nlp_engines.base import NLPEngine
from app.infra.nlp_snapshot_codec import (
    build_sentence_text_hash,
    count_snapshot_tokens,
    serialize_nlp_sentences,
)
from app.infra.nlp_engines.stanza_engine import create_stanza_engine
from app.domain.preprocessing import preprocess_text
from app.domain.sentence_splitter import split_into_sentences
from app.services.db_service import DBService
from app.services.entity_classifier import classify_text

logger = logging.getLogger(__name__)


class ProcessService:
    """Service for NLP document processing."""

    def __init__(self):
        self.db_service = DBService.get_instance()
        self._engine: Optional[NLPEngine] = None
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
        if self._engine is None:
            if use_mock:
                logger.info("Creating Mock NLP engine (rule-based)...")
                from app.infra.nlp_engines.mock_engine import create_mock_engine
                self._engine = create_mock_engine()
            else:
                logger.info("Creating Stanza NLP engine...")
                try:
                    self._engine = create_stanza_engine(use_gpu=use_gpu)
                except (ImportError, RuntimeError) as e:
                    logger.warning(f"Stanza not available: {e}")
                    logger.info("Falling back to Mock engine")
                    from app.infra.nlp_engines.mock_engine import create_mock_engine
                    self._engine = create_mock_engine()

            logger.info(f"NLP engine ready: {self._engine.get_name()} v{self._engine.get_version()}")
        return self._engine

    def _build_run_params_hash(
        self,
        *,
        engine: NLPEngine,
        use_gpu: bool,
        use_mock: bool,
        is_reprocess: bool,
        contract: str = "process_document_v2",
    ) -> str:
        payload = {
            "contract": str(contract or "process_document_v2"),
            "engine": engine.get_name(),
            "engine_version": engine.get_version(),
            "use_gpu": bool(use_gpu),
            "use_mock": bool(use_mock),
            "is_reprocess": bool(is_reprocess),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _build_doc_ids_hash(doc_ids: List[int]) -> str:
        encoded = json.dumps([int(doc_id) for doc_id in doc_ids], separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def _build_run_state_payload(
        self,
        run: ProcessorRun,
        *,
        phase: str,
        message: Optional[str] = None,
        doc_name: Optional[str] = None,
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
        state_callback: Optional[Callable[[dict[str, Any]], None]],
        run: ProcessorRun,
        *,
        phase: str,
        message: Optional[str] = None,
        doc_name: Optional[str] = None,
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
        doc_ids: List[int],
        chunk_size: int,
        source_label: str,
        is_reprocess: bool,
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
        return json.dumps(note, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _parse_batch_run_note(note: Optional[str]) -> dict[str, Any]:
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
        doc_ids: List[int],
        source_label: str,
        is_reprocess: bool,
    ) -> Optional[ProcessorRun]:
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
        doc_ids: List[int],
        source_label: str,
        is_reprocess: bool,
        require_incomplete: bool,
    ) -> tuple[bool, Optional[str], dict[str, Any]]:
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
        doc_ids: List[int],
        use_gpu: bool = False,
        use_mock: bool = False,
        *,
        is_reprocess: bool = False,
        source_label: str = "batch",
        resume_latest: bool = False,
        resume_run_id: Optional[int] = None,
        contract: str = "process_document_v2",
    ) -> dict[str, Any]:
        """Validate a batch NLP run contract without mutating the DB."""
        if resume_latest and resume_run_id is not None:
            raise ValueError("resume_latest and resume_run_id are mutually exclusive")

        ordered_ids = sorted({int(doc_id) for doc_id in doc_ids})
        if not ordered_ids:
            raise ValueError("doc_ids must not be empty")

        project_id = self._resolve_project_id_for_docs(session, ordered_ids)
        engine = self.get_nlp_engine(use_gpu=use_gpu, use_mock=use_mock)
        params_hash = self._build_run_params_hash(
            engine=engine,
            use_gpu=use_gpu,
            use_mock=use_mock,
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

    def _resolve_project_id_for_docs(self, session: Session, doc_ids: List[int]) -> int:
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

    def _upsert_sentence_nlp_snapshot(
        self,
        session: Session,
        *,
        sentence_row: DocumentSentence,
        engine: NLPEngine,
        nlp_sentences: List[Any],
    ) -> int:
        snapshot = session.get(SentenceNLPSnapshot, int(sentence_row.sentence_id))
        if snapshot is None:
            snapshot = SentenceNLPSnapshot(sentence_id=int(sentence_row.sentence_id))
            session.add(snapshot)

        snapshot.engine = engine.get_name()
        snapshot.engine_version = engine.get_version()
        snapshot.sentence_text_hash = build_sentence_text_hash(str(sentence_row.text or ""))
        snapshot.payload_json = serialize_nlp_sentences(nlp_sentences)
        snapshot.token_count = count_snapshot_tokens(nlp_sentences)
        return int(snapshot.token_count or 0)

    def _record_batch_run_error(
        self,
        session: Session,
        *,
        run_id: Optional[int],
        doc_id: Optional[int],
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

    def _start_processor_run(
        self,
        session: Session,
        *,
        project_id: int,
        engine: NLPEngine,
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
        is_reprocess: bool = False,
        track_run: bool = True,
        batch_run_id: Optional[int] = None,
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
        engine = self.get_nlp_engine(use_gpu=use_gpu, use_mock=use_mock)

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
            doc.status = 'processing'
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
            lemma_pos_map: Dict[str, str] = {}  # lemma_text -> most common POS
            lemma_sample_sentences: Dict[str, int] = {}  # lemma_text -> sentence_id

            # Get all sentences back with IDs
            stmt = select(DocumentSentence).where(
                DocumentSentence.doc_id == doc_id
            ).order_by(DocumentSentence.sent_index)
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
            doc.status = 'processed'
            doc.processed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            doc.sentence_count = len(sentences)
            doc.token_count = total_tokens
            session.commit()

            # Update run
            if run is not None:
                run.status = 'ok'
                run.stage = 'completed'
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
                    stage='processing',
                    message=error_msg,
                )
                session.add(error)

                # Re-fetch objects in clean state
                run_obj = session.get(ProcessorRun, run_id) if run_id is not None else None
                if run is not None and run_obj:
                    run_obj.status = 'failed'
                    run_obj.stage = 'failed'
                    run_obj.finished_at = self._utc_now()
                    run_obj.last_doc_id = doc_id
                    run_obj.docs_failed = 1
                    run_obj.error_message = error_msg

                doc_obj = session.get(SourceDocument, doc_id)
                if doc_obj:
                    doc_obj.status = 'failed'
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
        lemma_pos_map: Dict[str, str],
    ) -> Dict[str, int]:
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
        stats = {'new': 0, 'existing': 0, 'noise': 0, 'classes': Counter()}

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
                pos = lemma_pos_map.get(lemma_text, 'X')
                lemma = Lemma(
                    project_id=project_id,
                    lemma_text=lemma_text,
                    pos=pos,
                    entity_class=classification.entity_class,
                    is_noise=1 if classification.is_noise else 0,
                    noise_reason=classification.noise_reason,
                    norm_text=classification.norm_text,
                )
                session.add(lemma)
                session.flush()

                stats['new'] += 1
                stats['classes'][classification.entity_class] += 1
                if classification.is_noise:
                    stats['noise'] += 1

                logger.debug(f"Created lemma: {lemma_text} ({pos}) -> {classification.entity_class}")
            else:
                stats['existing'] += 1

            lemma_id_map[lemma_text] = lemma.lemma_id

        # Log classification summary
        if stats['new'] > 0:
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
        lemma_id_map: Dict[str, int],
        lemma_sample_sentences: Dict[str, int],
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
                proj_stat.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
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

    def _backfill_sentence_nlp_snapshots_for_document(
        self,
        session: Session,
        doc_id: int,
        *,
        engine: NLPEngine,
        batch_run_id: Optional[int] = None,
    ) -> tuple[bool, str]:
        """Persist missing sentence snapshots for one already-processed document."""
        logger.info("Backfilling sentence snapshots for document %s...", doc_id)

        try:
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
                return True, "No document_sentence rows to backfill"

            missing_count = 0
            token_total = 0
            for sent_row, snapshot in rows:
                if snapshot is not None:
                    continue
                missing_count += 1
                token_total += self._upsert_sentence_nlp_snapshot(
                    session,
                    sentence_row=sent_row,
                    engine=engine,
                    nlp_sentences=engine.process(str(sent_row.text or "")),
                )

            session.commit()
            if missing_count == 0:
                return True, "Snapshots already present"
            return True, (
                f"Backfilled {missing_count} sentence snapshot(s)"
                f" ({token_total} token(s))"
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
            return False, str(exc)

    def backfill_sentence_snapshots_batch(
        self,
        session: Session,
        doc_ids: List[int],
        use_gpu: bool = False,
        use_mock: bool = False,
        *,
        chunk_size: int = 50,
        chunk_sleep: float = 0.0,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        state_callback: Optional[Callable[[dict[str, Any]], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        pause_check: Optional[Callable[[], bool]] = None,
        resume_latest: bool = False,
        resume_run_id: Optional[int] = None,
        source_label: str = "snapshot_backfill",
    ) -> Tuple[int, int]:
        """Backfill missing sentence snapshots for a deterministic processed-doc slice."""
        if resume_latest and resume_run_id is not None:
            raise ValueError("resume_latest and resume_run_id are mutually exclusive")

        ordered_ids = sorted({int(doc_id) for doc_id in doc_ids})
        if not ordered_ids:
            return 0, 0
        if chunk_size <= 0:
            raise ValueError("chunk_size must be >= 1")

        project_id = self._resolve_project_id_for_docs(session, ordered_ids)
        engine = self.get_nlp_engine(use_gpu=use_gpu, use_mock=use_mock)
        params_hash = self._build_run_params_hash(
            engine=engine,
            use_gpu=use_gpu,
            use_mock=use_mock,
            is_reprocess=False,
            contract="snapshot_backfill_v1",
        )
        total_chunks = math.ceil(len(ordered_ids) / chunk_size)
        effective_chunk_size = int(chunk_size)

        run = None
        verification: Optional[dict[str, Any]] = None
        if resume_run_id is not None:
            verification = self.verify_batch_run_contract(
                session,
                ordered_ids,
                use_gpu=use_gpu,
                use_mock=use_mock,
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
                    f"{int(run.docs_failed)} document(s) failed during sentence snapshot backfill"
                )
            session.commit()
            session.refresh(run)
            self._emit_run_state(
                state_callback,
                run,
                phase="completed",
                message="No remaining documents for this sentence snapshot backfill run",
            )
            return 0, 0

        success = 0
        errors = 0

        def _cancel_current_run(message: str) -> Tuple[int, int]:
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
                done_before = int(run.docs_processed or 0) + int(run.docs_failed or 0)
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
                ok, detail = self._backfill_sentence_nlp_snapshots_for_document(
                    doc_session,
                    int(doc_id),
                    engine=engine,
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
            run.stage = "snapshot_backfill"
            session.commit()
            session.refresh(run)
            self._emit_run_state(
                state_callback,
                run,
                phase="processing",
                message=detail,
                doc_name=doc_name,
            )

            if docs_done % effective_chunk_size == 0:
                self._emit_run_state(
                    state_callback,
                    run,
                    phase="chunk_complete",
                    message=(
                        "Completed sentence snapshot backfill chunk "
                        f"{int(run.chunks_completed or 0)}/{int(run.chunks_total or 0)}"
                    ),
                )
                if chunk_sleep > 0 and docs_done < int(run.docs_total or 0):
                    time.sleep(chunk_sleep)

        run.status = "ok"
        run.stage = "completed_with_errors" if errors > 0 else "completed"
        run.finished_at = self._utc_now()
        run.chunks_completed = int(run.chunks_total or 0)
        run.error_message = (
            f"{errors} document(s) failed during sentence snapshot backfill"
            if errors > 0
            else None
        )
        session.commit()
        session.refresh(run)
        self._emit_run_state(
            state_callback,
            run,
            phase="completed",
            message="Sentence snapshot backfill run completed",
        )

        logger.info(
            "Sentence snapshot backfill complete: %d succeeded, %d failed (run_id=%d)",
            success,
            errors,
            int(run.run_id),
        )
        return success, errors

    def process_documents_batch(
        self,
        session: Session,
        doc_ids: List[int],
        use_gpu: bool = False,
        use_mock: bool = False,
        *,
        is_reprocess: bool = False,
        chunk_size: int = 50,
        chunk_sleep: float = 0.0,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        state_callback: Optional[Callable[[dict[str, Any]], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        pause_check: Optional[Callable[[], bool]] = None,
        resume_latest: bool = False,
        resume_run_id: Optional[int] = None,
        source_label: str = "batch",
    ) -> Tuple[int, int]:
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
        engine = self.get_nlp_engine(use_gpu=use_gpu, use_mock=use_mock)
        params_hash = self._build_run_params_hash(
            engine=engine,
            use_gpu=use_gpu,
            use_mock=use_mock,
            is_reprocess=is_reprocess,
        )
        total_chunks = math.ceil(len(ordered_ids) / chunk_size)
        effective_chunk_size = int(chunk_size)
        run_note: dict[str, Any] = {}

        run = None
        verification: Optional[dict[str, Any]] = None
        if resume_run_id is not None:
            verification = self.verify_batch_run_contract(
                session,
                ordered_ids,
                use_gpu=use_gpu,
                use_mock=use_mock,
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

        def _cancel_current_run(message: str) -> Tuple[int, int]:
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
                        track_run=False,
                        batch_run_id=int(run.run_id),
                    )
                else:
                    ok = self.process_document(
                        doc_session,
                        doc_id,
                        use_gpu=use_gpu,
                        use_mock=use_mock,
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
            f"{errors} document(s) failed during batch processing"
            if errors > 0
            else None
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

            doc_stats_count = int(
                session.execute(
                    text(
                        "SELECT COUNT(*) FROM lemma_doc_stat "
                        "WHERE project_id = :pid AND doc_id = :doc_id"
                    ),
                    {"pid": project_id, "doc_id": int(doc_id)},
                ).scalar()
                or 0
            )
            if doc_stats_count <= 0:
                logger.info("No statistics to remove")
                return True

            updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
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
                text(
                    "DELETE FROM lemma_doc_stat "
                    "WHERE project_id = :pid AND doc_id = :doc_id"
                ),
                params,
            )
            session.execute(
                text(
                    "DELETE FROM lemma_project_stat "
                    "WHERE project_id = :pid AND (freq_abs <= 0 OR doc_freq <= 0)"
                ),
                params,
            )

            # Delete lemmas that no longer have any project stats
            # (orphaned lemmas)
            self._cleanup_orphaned_lemmas(session, project_id)

            logger.info(f"Removed statistics for {doc_stats_count} lemmas")
            return True

        except Exception as e:
            logger.exception(f"Failed to remove document stats for {doc_id}")
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
                text(
                    "SELECT COUNT(*) FROM document_sentence WHERE doc_id = :doc_id"
                ),
                {"doc_id": int(doc_id)},
            ).scalar()
            or 0
        )
        if sentence_count <= 0:
            return 0

        params = {"doc_id": int(doc_id)}
        sentence_ids_sql = (
            "SELECT sentence_id FROM document_sentence WHERE doc_id = :doc_id"
        )

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
                f"DELETE FROM sentence_pronunciation "
                f"WHERE sentence_id IN ({sentence_ids_sql})"
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
        track_run: bool = True,
        batch_run_id: Optional[int] = None,
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

            if doc.status not in ('processed', 'failed'):
                logger.warning(f"Document {doc_id} is not processed (status: {doc.status})")
                # Allow reprocessing anyway (for failed docs)

            logger.info(f"Re-processing document {doc_id}: {doc.file_name}")

            # Step 1: Set status to 'processing'
            doc.status = 'processing'
            session.flush()

            # Step 2: Remove old statistics
            if not self.remove_document_stats(session, doc_id):
                logger.error(f"Failed to remove old stats for document {doc_id}")
                doc.status = 'failed'
                doc.error_message = "Failed to remove old statistics"
                session.commit()
                return False

            # Step 3: Delete old sentences
            deleted_sentences = self._clear_document_sentences_fast(session, doc_id)
            logger.info(f"Deleted {deleted_sentences} old sentences")

            # Step 4: Run NLP processing
            # Note: process_document will handle the rest
            # We need to temporarily reset status to 'imported' so process_document works
            doc.status = 'imported'
            doc.processed_at = None
            session.flush()

            # Process
            process_kwargs = {
                "use_gpu": use_gpu,
                "use_mock": use_mock,
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
            # Set status to failed
            doc = session.get(SourceDocument, doc_id)
            if doc:
                doc.status = 'failed'
                doc.error_message = f"Re-processing error: {str(e)}"
                session.commit()
            return False

    def bulk_reprocess(
        self,
        session: Session,
        doc_ids: List[int],
        use_gpu: bool = False,
        use_mock: bool = False,
    ) -> Tuple[int, int]:
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
            if self.reprocess_document(session, doc_id, use_gpu=use_gpu, use_mock=use_mock):
                success += 1
            else:
                errors += 1

        logger.info(f"Bulk re-processing complete: {success} succeeded, {errors} failed")
        return success, errors
