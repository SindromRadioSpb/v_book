"""Term Extraction Service (M5 Base + M5.1 Clustering)."""

import json
import logging
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import and_, bindparam, func, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.domain.dto import ClusterStats, ExtractReport, TermExtractionRunState
from app.domain.term_extraction.association_measures import compute_all_measures
from app.domain.term_extraction.canonicalizer import choose_representative_term, get_cluster_key
from app.domain.term_extraction.ngram_extractor import extract_ngrams_from_sentence
from app.domain.term_extraction.np_extractor import extract_np_chunks_from_sentence
from app.infra.nlp_engines.base import NLPEngine
from app.infra.nlp_snapshot_codec import build_sentence_text_hash, deserialize_nlp_sentences
from app.infra.sa_models import (
    DictProject,
    DocumentSentence,
    Lemma,
    LemmaProjectStat,
    Ngram,
    NgramProjectStat,
    SentenceNLPSnapshot,
    SourceCorpus,
    SourceDocument,
    TermCluster,
    TermClusterMember,
    TermExtractAccumulator,
    TermExtractRun,
    TMEntry,
)
from app.services.db_service import DBService
from app.services.entity_classifier import classify_phrase

logger = logging.getLogger(__name__)


def normalize_search_query(query: str) -> list[str]:
    """
    Normalize search query and generate search variants for Hebrew term matching.

    Generates multiple normalized variants to handle:
    - Definite article variations ("הספר" vs "ספר")
    - Space vs underscore separators ("בית ספר" vs "בית_ספר")
    - Attached vs standalone articles ("בית הספר" vs "בית ה ספר")

    Args:
        query: Raw search query from user

    Returns:
        List of normalized search variants

    Examples:
        "בית הספר" → ["בית הספר", "בית ספר", "בית_הספר", "בית_ספר"]
        "הספר" → ["הספר", "ספר", "הספר", "ספר"]
    """
    from app.domain.hebrew_utils import normalize_whitespace, strip_cantillation, strip_nikud

    if not query or not query.strip():
        return []

    # Basic normalization
    normalized = strip_nikud(query)
    normalized = strip_cantillation(normalized)
    normalized = normalize_whitespace(normalized)
    normalized = normalized.strip()

    variants = set()

    # Original normalized query
    variants.add(normalized)

    # Underscore version (for canonical_key matching)
    underscore_version = normalized.replace(" ", "_")
    variants.add(underscore_version)

    # Article-stripped variants
    # Remove standalone "ה" tokens
    tokens = normalized.split()
    filtered_tokens = [t for t in tokens if t != "ה"]
    if filtered_tokens != tokens:
        article_stripped = " ".join(filtered_tokens)
        variants.add(article_stripped)
        variants.add(article_stripped.replace(" ", "_"))

    # Also strip attached articles (הX → X) for each token
    article_stripped_tokens = []
    for token in tokens:
        if token.startswith("ה") and len(token) > 1:
            # Strip leading ה
            article_stripped_tokens.append(token[1:])
        else:
            article_stripped_tokens.append(token)

    if article_stripped_tokens != tokens:
        article_stripped_2 = " ".join(article_stripped_tokens)
        variants.add(article_stripped_2)
        variants.add(article_stripped_2.replace(" ", "_"))

    return list(variants)


class TermExtractionService:
    """Service for term extraction and clustering (M5+)."""

    def __init__(self):
        self.db_service = DBService.get_instance()
        self._engine: NLPEngine | None = None

    def get_nlp_engine(self, use_gpu: bool = False, use_mock: bool = False) -> NLPEngine:
        """
        Get or create NLP engine for re-parsing sentences.

        Args:
            use_gpu: Whether to use GPU
            use_mock: Use mock engine instead of Stanza

        Returns:
            NLPEngine instance
        """
        if self._engine is None:
            if use_mock:
                logger.info("Creating Mock NLP engine for term extraction...")
                from app.infra.nlp_engines.mock_engine import create_mock_engine

                self._engine = create_mock_engine()
            else:
                logger.info("Creating Stanza NLP engine for term extraction...")
                try:
                    from app.infra.nlp_engines.stanza_engine import create_stanza_engine

                    self._engine = create_stanza_engine(use_gpu=use_gpu)
                except (ImportError, RuntimeError) as e:
                    logger.warning(f"Stanza not available: {e}")
                    logger.info("Falling back to Mock engine")
                    from app.infra.nlp_engines.mock_engine import create_mock_engine

                    self._engine = create_mock_engine()

            logger.info(
                f"NLP engine ready: {self._engine.get_name()} v{self._engine.get_version()}"
            )
        return self._engine

    def _build_run_state_payload(
        self,
        run: TermExtractRun | None,
        *,
        project_id: int,
        phase: str,
        message: str | None = None,
        docs_processed: int = 0,
        docs_total: int = 0,
        chunks_completed: int = 0,
        chunks_total: int = 0,
        last_doc_id: int | None = None,
    ) -> dict:
        payload = asdict(
            TermExtractionRunState(
                run_id=int(run.run_id) if run is not None else 0,
                project_id=int(project_id),
                status=str(getattr(run, "status", "") or ""),
                stage=getattr(run, "stage", None),
                docs_total=int(docs_total),
                docs_processed=int(docs_processed),
                docs_failed=0,
                chunks_total=int(chunks_total),
                chunks_completed=int(chunks_completed),
                last_doc_id=(
                    int(last_doc_id)
                    if last_doc_id is not None
                    else (
                        int(run.last_doc_id)
                        if run is not None and getattr(run, "last_doc_id", None) is not None
                        else None
                    )
                ),
                error_message=getattr(run, "error_message", None),
            )
        )
        payload["phase"] = str(phase or "")
        if message is not None:
            payload["message"] = message
        return payload

    @staticmethod
    def _snapshot_reuse_pct(snapshot_rows_used: int, reparsed_sentences: int) -> float | None:
        total = int(snapshot_rows_used or 0) + int(reparsed_sentences or 0)
        if total <= 0:
            return None
        return round(int(snapshot_rows_used or 0) / total * 100.0, 4)

    def extract_terms_for_project(
        self,
        session: Session,
        project_id: int,
        *,
        enable_ngrams: bool = True,
        include_np: bool = False,
        min_freq: int = 2,
        ngram_ns: tuple[int, ...] = (2, 3),
        np_max_len: int = 5,
        overwrite: bool = True,
        batch_size: int = 200,
        progress_callback: Callable[[str], None] | None = None,
        state_callback: Callable[[dict], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        pause_check: Callable[[], bool] | None = None,
        resume_latest: bool = True,
    ) -> ExtractReport:
        """
        Extract terms (n-grams + NP chunks + clustering) for a project.

        Args:
            session: DB session
            project_id: Project ID
            enable_ngrams: Extract n-grams
            include_np: Extract NP chunks (M5.3)
            min_freq: Minimum frequency threshold
            ngram_ns: N-gram sizes (default: bigrams + trigrams)
            np_max_len: Maximum NP chunk length (2-5, default 5)
            overwrite: Clear existing ngrams before extraction
            batch_size: Number of processed docs to stage per commit
            progress_callback: Optional human-readable progress callback
            state_callback: Optional structured progress callback
            cancel_check: Optional cooperative cancel callback
            pause_check: Optional cooperative pause callback
            resume_latest: Resume latest matching staged run when possible

        Returns:
            ExtractReport with counts
        """
        if not overwrite:
            # Non-overwrite mode is legacy-only: final term tables use unique
            # constraints keyed by project/source_kind/surface and cannot be
            # safely merged from staged counters without a wider redesign.
            return self._extract_terms_for_project_legacy(
                session,
                project_id,
                enable_ngrams=enable_ngrams,
                include_np=include_np,
                min_freq=min_freq,
                ngram_ns=ngram_ns,
                np_max_len=np_max_len,
                overwrite=overwrite,
            )

        return self._extract_terms_for_project_chunked(
            session,
            project_id,
            enable_ngrams=enable_ngrams,
            include_np=include_np,
            min_freq=min_freq,
            ngram_ns=ngram_ns,
            np_max_len=np_max_len,
            overwrite=overwrite,
            batch_size=batch_size,
            progress_callback=progress_callback,
            state_callback=state_callback,
            cancel_check=cancel_check,
            pause_check=pause_check,
            resume_latest=resume_latest,
        )

    def _extract_terms_for_project_legacy(
        self,
        session: Session,
        project_id: int,
        *,
        enable_ngrams: bool,
        include_np: bool,
        min_freq: int,
        ngram_ns: tuple[int, ...],
        np_max_len: int,
        overwrite: bool,
    ) -> ExtractReport:
        """Legacy monolithic extractor retained for non-overwrite compatibility."""
        logger.info(f"Starting legacy term extraction for project {project_id}")

        try:
            # Get project
            project = session.get(DictProject, project_id)
            if not project:
                raise ValueError(f"Project {project_id} not found")

            # Read/compute first, then perform one bounded write phase.
            snapshot_usage = {"snapshot_rows_used": 0, "reparsed_sentences": 0}
            ngram_counts = Counter()
            ngram_doc_freq = Counter()
            ngram_meta: dict[tuple[str, int], dict[str, str]] = {}
            ngrams_extracted = 0
            if enable_ngrams:
                ngram_counts, ngram_doc_freq, ngram_meta = self._collect_ngrams(
                    session, project_id, ngram_ns, min_freq, summary=snapshot_usage
                )

            np_counts = Counter()
            np_doc_freq = Counter()
            np_meta: dict[tuple[str, int], dict[str, str]] = {}
            np_chunks_extracted = 0
            if include_np:
                np_counts, np_doc_freq, np_meta = self._collect_np_chunks(
                    session, project_id, np_max_len, min_freq, summary=snapshot_usage
                )

            # Clear existing only after read phase succeeded, so overwrite keeps
            # rollback safety if collection fails on large projects.
            if overwrite:
                self._clear_existing_terms(session, project_id)

            if enable_ngrams:
                ngrams_extracted = self._store_ngrams(
                    session,
                    project_id,
                    ngram_counts=ngram_counts,
                    ngram_doc_freq=ngram_doc_freq,
                    ngram_meta=ngram_meta,
                    min_freq=min_freq,
                )

            if include_np:
                np_chunks_extracted = self._store_np_chunks(
                    session,
                    project_id,
                    np_counts=np_counts,
                    np_doc_freq=np_doc_freq,
                    np_meta=np_meta,
                    min_freq=min_freq,
                )

            # Cluster terms
            clusters_created = self._cluster_terms(session, project_id)

            # Migration 011: Save extraction parameters for UX feedback
            from datetime import datetime

            project.last_extract_np_max_len = np_max_len
            project.last_extract_min_freq = min_freq
            project.last_extract_include_np = 1 if include_np else 0
            project.last_extract_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            project.updated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

            session.commit()

            logger.info(
                f"Extraction complete: {ngrams_extracted} ngrams, "
                f"{np_chunks_extracted} NP chunks, {clusters_created} clusters"
            )

            return ExtractReport(
                project_id=project_id,
                ngrams_extracted=ngrams_extracted,
                np_chunks_extracted=np_chunks_extracted,
                clusters_created=clusters_created,
                success=True,
                snapshot_rows_used=int(snapshot_usage["snapshot_rows_used"]),
                reparsed_sentences=int(snapshot_usage["reparsed_sentences"]),
                snapshot_reuse_pct=self._snapshot_reuse_pct(
                    snapshot_usage["snapshot_rows_used"],
                    snapshot_usage["reparsed_sentences"],
                ),
            )

        except Exception as e:
            logger.exception(f"Legacy term extraction failed for project {project_id}")
            session.rollback()
            return ExtractReport(
                project_id=project_id,
                ngrams_extracted=0,
                np_chunks_extracted=0,
                clusters_created=0,
                success=False,
                error_message=str(e),
                snapshot_rows_used=0,
                reparsed_sentences=0,
                snapshot_reuse_pct=None,
            )

    def _extract_terms_for_project_chunked(
        self,
        session: Session,
        project_id: int,
        *,
        enable_ngrams: bool,
        include_np: bool,
        min_freq: int,
        ngram_ns: tuple[int, ...],
        np_max_len: int,
        overwrite: bool,
        batch_size: int,
        progress_callback: Callable[[str], None] | None,
        state_callback: Callable[[dict], None] | None,
        cancel_check: Callable[[], bool] | None,
        pause_check: Callable[[], bool] | None,
        resume_latest: bool,
    ) -> ExtractReport:
        """Chunked staged extractor for large projects."""

        run_id: int | None = None
        total_docs = 0
        docs_processed = 0
        run: TermExtractRun | None = None
        snapshot_usage = {"snapshot_rows_used": 0, "reparsed_sentences": 0}

        def _emit(
            message: str,
            *,
            stage: str | None = None,
            phase: str | None = None,
            docs_done: int | None = None,
            docs_hint: int | None = None,
            chunks_done: int | None = None,
            chunks_hint: int | None = None,
            last_doc_id: int | None = None,
        ) -> None:
            logger.info(message)
            if progress_callback:
                progress_callback(message)
            if state_callback:
                if run is not None and stage is not None:
                    run.stage = stage
                state_callback(
                    self._build_run_state_payload(
                        run,
                        project_id=project_id,
                        phase=phase or "",
                        message=message,
                        docs_processed=int(
                            docs_done
                            if docs_done is not None
                            else (
                                int(getattr(run, "docs_processed", 0) or 0)
                                if run is not None
                                else docs_processed
                            )
                        ),
                        docs_total=int(
                            docs_hint
                            if docs_hint is not None
                            else (
                                int(getattr(run, "docs_total", 0) or 0)
                                if run is not None
                                else total_docs
                            )
                        ),
                        chunks_completed=int(
                            chunks_done
                            if chunks_done is not None
                            else int(getattr(run, "chunks_completed", 0) or 0)
                        ),
                        chunks_total=int(
                            chunks_hint
                            if chunks_hint is not None
                            else int(getattr(run, "chunks_total", 0) or 0)
                        ),
                        last_doc_id=last_doc_id,
                    )
                )

        try:
            project = session.get(DictProject, project_id)
            if not project:
                raise ValueError(f"Project {project_id} not found")

            batch_size = max(1, int(batch_size or 1))
            total_docs = self._count_processed_docs(session, project_id)

            if resume_latest:
                run = self._find_resumable_term_extract_run(
                    session,
                    project_id,
                    enable_ngrams=enable_ngrams,
                    include_np=include_np,
                    min_freq=min_freq,
                    ngram_ns=ngram_ns,
                    np_max_len=np_max_len,
                    overwrite=overwrite,
                )
                if run is not None and run.status not in ("staged", "finalizing"):
                    if int(run.docs_total or 0) != int(total_docs):
                        logger.info(
                            "Ignoring resumable term extraction run %s for project %s "
                            "because processed-doc count changed (%s -> %s)",
                            run.run_id,
                            project_id,
                            run.docs_total,
                            total_docs,
                        )
                        run = None

            if run is None:
                run = self._create_term_extract_run(
                    session,
                    project_id,
                    enable_ngrams=enable_ngrams,
                    include_np=include_np,
                    min_freq=min_freq,
                    ngram_ns=ngram_ns,
                    np_max_len=np_max_len,
                    overwrite=overwrite,
                    docs_total=total_docs,
                    batch_size=batch_size,
                )
                run_id = int(run.run_id)
                _emit(
                    f"Created term extraction run {run.run_id} for {total_docs} docs",
                    stage="Preparing staged extraction",
                    phase="prepare",
                    docs_done=0,
                    docs_hint=total_docs,
                    chunks_done=0,
                    chunks_hint=int(run.chunks_total or 0),
                )
            else:
                run.docs_total = int(total_docs)
                run.chunks_total = self._estimate_term_extract_chunks(total_docs, batch_size)
                run.status = "running" if run.status not in ("staged", "finalizing") else run.status
                run.stage = "Resuming staged extraction"
                run.error_message = None
                run.updated_at = self._utc_now()
                session.commit()
                run_id = int(run.run_id)
                _emit(
                    f"Resuming term extraction run {run.run_id} "
                    f"at doc {int(run.docs_processed or 0)}/{int(run.docs_total or 0)}",
                    stage="Resuming staged extraction",
                    phase="prepare",
                    docs_done=int(run.docs_processed or 0),
                    docs_hint=int(run.docs_total or 0),
                    chunks_done=int(run.chunks_completed or 0),
                    chunks_hint=int(run.chunks_total or 0),
                    last_doc_id=(int(run.last_doc_id) if run.last_doc_id is not None else None),
                )

            run_id = int(run.run_id)
            docs_processed = int(run.docs_processed or 0)

            if total_docs == 0:
                self._clear_existing_terms(session, project_id)
                self._update_extract_project_metadata(
                    project,
                    min_freq=min_freq,
                    include_np=include_np,
                    np_max_len=np_max_len,
                )
                run.status = "ok"
                run.stage = "Completed (no processed docs)"
                run.finished_at = self._utc_now()
                run.updated_at = run.finished_at
                session.commit()
                _emit(
                    "No processed docs found; staged extraction completed immediately",
                    stage="Completed",
                    phase="completed",
                    docs_done=0,
                    docs_hint=0,
                    chunks_done=0,
                    chunks_hint=0,
                )
                return ExtractReport(
                    project_id=project_id,
                    ngrams_extracted=0,
                    np_chunks_extracted=0,
                    clusters_created=0,
                    success=True,
                    run_id=run_id,
                    docs_processed=0,
                    docs_total=0,
                    snapshot_rows_used=0,
                    reparsed_sentences=0,
                    snapshot_reuse_pct=None,
                )

            use_mock = (
                project.nlp_engine.lower() == "mock" if project and project.nlp_engine else False
            )
            engine = self.get_nlp_engine(use_mock=use_mock)
            run.engine = engine.get_name()
            run.engine_version = engine.get_version()
            run.updated_at = self._utc_now()
            session.commit()

            if (
                run.status not in ("staged", "finalizing")
                and int(run.docs_processed or 0) < total_docs
            ):
                _emit(
                    f"Collecting staged counters for run {run_id}: "
                    f"{docs_processed}/{total_docs} docs complete",
                    stage="Collecting staged counters",
                    phase="collect",
                    docs_done=docs_processed,
                    docs_hint=total_docs,
                    chunks_done=int(run.chunks_completed or 0),
                    chunks_hint=int(run.chunks_total or 0),
                    last_doc_id=(int(run.last_doc_id) if run.last_doc_id is not None else None),
                )
                while True:
                    resume_stage = "Collecting staged counters"

                    def _on_paused() -> None:
                        if run is None:
                            return
                        run.stage = "Paused at batch checkpoint"
                        run.updated_at = self._utc_now()
                        session.commit()
                        _emit(
                            "Paused at batch checkpoint; waiting for resume",
                            stage=run.stage,
                            phase="paused",
                            docs_done=int(run.docs_processed or 0),
                            docs_hint=total_docs,
                            chunks_done=int(run.chunks_completed or 0),
                            chunks_hint=int(run.chunks_total or 0),
                            last_doc_id=(
                                int(run.last_doc_id) if run.last_doc_id is not None else None
                            ),
                        )

                    def _on_resumed() -> None:
                        if run is None:
                            return
                        run.stage = resume_stage
                        run.updated_at = self._utc_now()
                        session.commit()
                        _emit(
                            "Resumed staged extraction",
                            stage=run.stage,
                            phase="resumed",
                            docs_done=int(run.docs_processed or 0),
                            docs_hint=total_docs,
                            chunks_done=int(run.chunks_completed or 0),
                            chunks_hint=int(run.chunks_total or 0),
                            last_doc_id=(
                                int(run.last_doc_id) if run.last_doc_id is not None else None
                            ),
                        )

                    if self._wait_if_paused(
                        pause_check=pause_check,
                        cancel_check=cancel_check,
                        on_paused=_on_paused,
                        on_resumed=_on_resumed,
                    ):
                        _emit(
                            "Cancellation requested; keeping staged progress for resume",
                            stage="Cancelled",
                            phase="cancelled",
                            docs_done=int(run.docs_processed or 0),
                            docs_hint=total_docs,
                            chunks_done=int(run.chunks_completed or 0),
                            chunks_hint=int(run.chunks_total or 0),
                            last_doc_id=(
                                int(run.last_doc_id) if run.last_doc_id is not None else None
                            ),
                        )
                        return self._cancel_term_extract_run(
                            session,
                            run_id=run_id,
                            project_id=project_id,
                            docs_processed=int(run.docs_processed or 0),
                            docs_total=total_docs,
                            snapshot_rows_used=int(snapshot_usage["snapshot_rows_used"]),
                            reparsed_sentences=int(snapshot_usage["reparsed_sentences"]),
                        )

                    doc_batch = self._fetch_processed_doc_batch(
                        session,
                        project_id,
                        last_doc_id=run.last_doc_id,
                        limit=batch_size,
                    )
                    if not doc_batch:
                        break

                    batch_no = int(run.chunks_completed or 0) + 1
                    batch_total = self._estimate_term_extract_chunks(total_docs, batch_size)
                    _emit(
                        f"Collecting batch {batch_no}/{batch_total} "
                        f"({len(doc_batch)} docs, up to doc {doc_batch[-1]})",
                        stage=f"Collecting batch {batch_no}/{batch_total}",
                        phase="collect",
                        docs_done=int(run.docs_processed or 0),
                        docs_hint=total_docs,
                        chunks_done=int(run.chunks_completed or 0),
                        chunks_hint=batch_total,
                        last_doc_id=int(doc_batch[-1]),
                    )

                    if enable_ngrams:
                        batch_ngram_counts, batch_ngram_doc_freq, batch_ngram_meta = (
                            self._collect_ngrams_for_doc_ids(
                                session,
                                doc_batch,
                                ngram_ns=ngram_ns,
                                engine=engine,
                                summary=snapshot_usage,
                            )
                        )
                        self._upsert_term_extract_accumulators(
                            session,
                            run_id=run_id,
                            source_kind="ngram",
                            counts=batch_ngram_counts,
                            doc_freq=batch_ngram_doc_freq,
                            meta=batch_ngram_meta,
                        )

                    if include_np:
                        batch_np_counts, batch_np_doc_freq, batch_np_meta = (
                            self._collect_np_chunks_for_doc_ids(
                                session,
                                doc_batch,
                                np_max_len=np_max_len,
                                engine=engine,
                                summary=snapshot_usage,
                            )
                        )
                        self._upsert_term_extract_accumulators(
                            session,
                            run_id=run_id,
                            source_kind="np",
                            counts=batch_np_counts,
                            doc_freq=batch_np_doc_freq,
                            meta=batch_np_meta,
                        )

                    run.docs_processed = int(run.docs_processed or 0) + len(doc_batch)
                    run.chunks_completed = int(run.chunks_completed or 0) + 1
                    run.chunks_total = batch_total
                    run.last_doc_id = int(doc_batch[-1])
                    run.stage = f"Collected {run.docs_processed}/{total_docs} docs"
                    run.status = "running"
                    run.updated_at = self._utc_now()
                    session.commit()
                    docs_processed = int(run.docs_processed or 0)
                    _emit(
                        f"Staged {docs_processed}/{total_docs} docs for run {run_id}",
                        stage=run.stage,
                        phase="collect",
                        docs_done=docs_processed,
                        docs_hint=total_docs,
                        chunks_done=int(run.chunks_completed or 0),
                        chunks_hint=batch_total,
                        last_doc_id=int(run.last_doc_id) if run.last_doc_id is not None else None,
                    )

                run.status = "staged"
                run.stage = "Staged counters ready"
                run.updated_at = self._utc_now()
                session.commit()
                _emit(
                    f"Staged counters are ready for run {run_id}",
                    stage=run.stage,
                    phase="staged",
                    docs_done=int(run.docs_processed or 0),
                    docs_hint=total_docs,
                    chunks_done=int(run.chunks_completed or 0),
                    chunks_hint=int(run.chunks_total or 0),
                    last_doc_id=int(run.last_doc_id) if run.last_doc_id is not None else None,
                )

            if cancel_check and cancel_check():
                _emit(
                    "Cancellation requested; staged progress saved before finalization",
                    stage="Cancelled",
                    phase="cancelled",
                    docs_done=int(run.docs_processed or 0),
                    docs_hint=total_docs,
                    chunks_done=int(run.chunks_completed or 0),
                    chunks_hint=int(run.chunks_total or 0),
                    last_doc_id=int(run.last_doc_id) if run.last_doc_id is not None else None,
                )
                return self._cancel_term_extract_run(
                    session,
                    run_id=run_id,
                    project_id=project_id,
                    docs_processed=int(run.docs_processed or 0),
                    docs_total=total_docs,
                    snapshot_rows_used=int(snapshot_usage["snapshot_rows_used"]),
                    reparsed_sentences=int(snapshot_usage["reparsed_sentences"]),
                )

            run.status = "finalizing"
            run.stage = "Finalizing staged counters"
            run.updated_at = self._utc_now()
            session.commit()

            _emit(
                "Finalizing staged counters into term tables "
                "(cancel is deferred until finalization completes)",
                stage="Finalizing staged counters",
                phase="finalize",
                docs_done=total_docs,
                docs_hint=total_docs,
                chunks_done=int(run.chunks_completed or 0),
                chunks_hint=int(run.chunks_total or 0),
                last_doc_id=int(run.last_doc_id) if run.last_doc_id is not None else None,
            )

            self._clear_existing_terms(session, project_id)
            total_tokens = self._get_total_tokens(session, project_id)
            ngrams_extracted = (
                self._store_staged_ngrams(
                    session,
                    project_id,
                    run_id=run_id,
                    min_freq=min_freq,
                    total_tokens=total_tokens,
                    progress_callback=lambda message: _emit(
                        message,
                        stage="Storing staged n-grams",
                        phase="finalize",
                        docs_done=total_docs,
                        docs_hint=total_docs,
                        chunks_done=int(run.chunks_completed or 0),
                        chunks_hint=int(run.chunks_total or 0),
                        last_doc_id=int(run.last_doc_id) if run.last_doc_id is not None else None,
                    ),
                )
                if enable_ngrams
                else 0
            )

            np_chunks_extracted = (
                self._store_staged_np_chunks(
                    session,
                    project_id,
                    run_id=run_id,
                    min_freq=min_freq,
                    progress_callback=lambda message: _emit(
                        message,
                        stage="Storing staged NP chunks",
                        phase="finalize",
                        docs_done=total_docs,
                        docs_hint=total_docs,
                        chunks_done=int(run.chunks_completed or 0),
                        chunks_hint=int(run.chunks_total or 0),
                        last_doc_id=int(run.last_doc_id) if run.last_doc_id is not None else None,
                    ),
                )
                if include_np
                else 0
            )

            _emit(
                "Clustering staged terms...",
                stage="Clustering staged terms",
                phase="finalize",
                docs_done=total_docs,
                docs_hint=total_docs,
                chunks_done=int(run.chunks_completed or 0),
                chunks_hint=int(run.chunks_total or 0),
                last_doc_id=int(run.last_doc_id) if run.last_doc_id is not None else None,
            )
            clusters_created = self._cluster_terms(session, project_id)

            self._update_extract_project_metadata(
                project,
                min_freq=min_freq,
                include_np=include_np,
                np_max_len=np_max_len,
            )

            session.execute(
                TermExtractAccumulator.__table__.delete().where(
                    TermExtractAccumulator.run_id == run_id
                )
            )
            run.status = "ok"
            run.stage = "Completed"
            run.error_message = None
            run.finished_at = self._utc_now()
            run.updated_at = run.finished_at
            session.commit()

            _emit(
                f"Chunked term extraction complete: {ngrams_extracted} ngrams, "
                f"{np_chunks_extracted} NP chunks, {clusters_created} clusters",
                stage="Completed",
                phase="completed",
                docs_done=int(run.docs_processed or 0),
                docs_hint=total_docs,
                chunks_done=int(run.chunks_completed or 0),
                chunks_hint=int(run.chunks_total or 0),
                last_doc_id=int(run.last_doc_id) if run.last_doc_id is not None else None,
            )

            return ExtractReport(
                project_id=project_id,
                ngrams_extracted=ngrams_extracted,
                np_chunks_extracted=np_chunks_extracted,
                clusters_created=clusters_created,
                success=True,
                run_id=run_id,
                docs_processed=int(run.docs_processed or 0),
                docs_total=total_docs,
                snapshot_rows_used=int(snapshot_usage["snapshot_rows_used"]),
                reparsed_sentences=int(snapshot_usage["reparsed_sentences"]),
                snapshot_reuse_pct=self._snapshot_reuse_pct(
                    snapshot_usage["snapshot_rows_used"],
                    snapshot_usage["reparsed_sentences"],
                ),
            )

        except Exception as e:
            logger.exception("Chunked term extraction failed for project %s", project_id)
            session.rollback()
            if run_id is not None:
                self._mark_term_extract_run_failed(
                    session,
                    run_id=run_id,
                    error_message=str(e),
                )
            return ExtractReport(
                project_id=project_id,
                ngrams_extracted=0,
                np_chunks_extracted=0,
                clusters_created=0,
                success=False,
                error_message=str(e),
                run_id=run_id,
                docs_processed=docs_processed,
                docs_total=total_docs,
                snapshot_rows_used=int(snapshot_usage["snapshot_rows_used"]),
                reparsed_sentences=int(snapshot_usage["reparsed_sentences"]),
                snapshot_reuse_pct=self._snapshot_reuse_pct(
                    snapshot_usage["snapshot_rows_used"],
                    snapshot_usage["reparsed_sentences"],
                ),
            )

    def _clear_existing_terms(self, session: Session, project_id: int) -> None:
        """Clear existing ngrams and clusters for project."""
        # Delete clusters (CASCADE handles members)
        session.execute(TermCluster.__table__.delete().where(TermCluster.project_id == project_id))

        # Delete ngrams (CASCADE handles stats and components)
        session.execute(Ngram.__table__.delete().where(Ngram.project_id == project_id))

        session.flush()
        logger.info(f"Cleared existing terms for project {project_id}")

    def _utc_now(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def _serialize_ngram_ns(self, ngram_ns: tuple[int, ...]) -> str:
        return json.dumps([int(value) for value in ngram_ns], separators=(",", ":"))

    def _count_processed_docs(self, session: Session, project_id: int) -> int:
        stmt = (
            select(func.count(SourceDocument.doc_id))
            .select_from(SourceDocument)
            .join(SourceCorpus)
            .where(
                and_(
                    SourceCorpus.project_id == project_id,
                    SourceDocument.status == "processed",
                )
            )
        )
        return int(session.execute(stmt).scalar() or 0)

    def _estimate_term_extract_chunks(self, docs_total: int, batch_size: int) -> int:
        if docs_total <= 0:
            return 0
        return (int(docs_total) + int(batch_size) - 1) // int(batch_size)

    def _find_resumable_term_extract_run(
        self,
        session: Session,
        project_id: int,
        *,
        enable_ngrams: bool,
        include_np: bool,
        min_freq: int,
        ngram_ns: tuple[int, ...],
        np_max_len: int,
        overwrite: bool,
    ) -> TermExtractRun | None:
        stmt = (
            select(TermExtractRun)
            .where(
                and_(
                    TermExtractRun.project_id == project_id,
                    TermExtractRun.enable_ngrams == (1 if enable_ngrams else 0),
                    TermExtractRun.include_np == (1 if include_np else 0),
                    TermExtractRun.overwrite == (1 if overwrite else 0),
                    TermExtractRun.min_freq == int(min_freq),
                    TermExtractRun.ngram_ns_json == self._serialize_ngram_ns(ngram_ns),
                    TermExtractRun.np_max_len == int(np_max_len),
                    TermExtractRun.status.in_(
                        ("running", "staged", "finalizing", "failed", "cancelled")
                    ),
                )
            )
            .order_by(TermExtractRun.run_id.desc())
        )
        return session.execute(stmt).scalars().first()

    def _create_term_extract_run(
        self,
        session: Session,
        project_id: int,
        *,
        enable_ngrams: bool,
        include_np: bool,
        min_freq: int,
        ngram_ns: tuple[int, ...],
        np_max_len: int,
        overwrite: bool,
        docs_total: int,
        batch_size: int,
    ) -> TermExtractRun:
        run = TermExtractRun(
            project_id=project_id,
            status="running",
            stage="Preparing staged extraction",
            enable_ngrams=1 if enable_ngrams else 0,
            include_np=1 if include_np else 0,
            overwrite=1 if overwrite else 0,
            min_freq=int(min_freq),
            ngram_ns_json=self._serialize_ngram_ns(ngram_ns),
            np_max_len=int(np_max_len),
            docs_total=int(docs_total),
            docs_processed=0,
            chunks_total=self._estimate_term_extract_chunks(docs_total, batch_size),
            chunks_completed=0,
        )
        session.add(run)
        session.commit()
        return run

    def _mark_term_extract_run_failed(
        self,
        session: Session,
        *,
        run_id: int,
        error_message: str,
    ) -> None:
        try:
            run = session.get(TermExtractRun, run_id)
            if not run:
                return
            run.status = "failed"
            run.error_message = error_message[:2000]
            run.stage = "Failed"
            run.updated_at = self._utc_now()
            run.finished_at = None
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("Failed to mark term extraction run %s as failed", run_id)

    def _cancel_term_extract_run(
        self,
        session: Session,
        *,
        run_id: int,
        project_id: int,
        docs_processed: int,
        docs_total: int,
        snapshot_rows_used: int = 0,
        reparsed_sentences: int = 0,
    ) -> ExtractReport:
        run = session.get(TermExtractRun, run_id)
        if run:
            run.status = "cancelled"
            run.stage = "Cancelled during staged collection"
            run.error_message = "Cancelled by user"
            run.updated_at = self._utc_now()
            session.commit()
        return ExtractReport(
            project_id=project_id,
            ngrams_extracted=0,
            np_chunks_extracted=0,
            clusters_created=0,
            success=False,
            error_message="Cancelled by user",
            cancelled=True,
            run_id=run_id,
            docs_processed=docs_processed,
            docs_total=docs_total,
            snapshot_rows_used=int(snapshot_rows_used or 0),
            reparsed_sentences=int(reparsed_sentences or 0),
            snapshot_reuse_pct=self._snapshot_reuse_pct(
                snapshot_rows_used,
                reparsed_sentences,
            ),
        )

    def _wait_if_paused(
        self,
        *,
        pause_check: Callable[[], bool] | None,
        cancel_check: Callable[[], bool] | None,
        on_paused: Callable[[], None] | None = None,
        on_resumed: Callable[[], None] | None = None,
    ) -> bool:
        was_paused = False
        while pause_check and pause_check():
            if not was_paused:
                was_paused = True
                if on_paused:
                    on_paused()
            if cancel_check and cancel_check():
                return True
            time.sleep(0.1)
        if was_paused and on_resumed:
            on_resumed()
        return bool(cancel_check and cancel_check())

    def _update_extract_project_metadata(
        self,
        project: DictProject,
        *,
        min_freq: int,
        include_np: bool,
        np_max_len: int,
    ) -> None:
        project.last_extract_np_max_len = int(np_max_len)
        project.last_extract_min_freq = int(min_freq)
        project.last_extract_include_np = 1 if include_np else 0
        project.last_extract_at = self._utc_now()
        project.updated_at = self._utc_now()

    def _fetch_processed_doc_batch(
        self,
        session: Session,
        project_id: int,
        *,
        last_doc_id: int | None,
        limit: int,
    ) -> list[int]:
        stmt = (
            select(SourceDocument.doc_id)
            .join(SourceCorpus)
            .where(
                and_(
                    SourceCorpus.project_id == project_id,
                    SourceDocument.status == "processed",
                )
            )
            .order_by(SourceDocument.doc_id.asc())
            .limit(int(limit))
        )
        if last_doc_id is not None:
            stmt = stmt.where(SourceDocument.doc_id > int(last_doc_id))
        return [int(value) for value in session.execute(stmt).scalars().all()]

    def _iter_processed_doc_ids(self, session: Session, project_id: int) -> Iterable[int]:
        """Yield processed document ids without materializing the whole project."""
        stmt = (
            select(SourceDocument.doc_id)
            .join(SourceCorpus)
            .where(
                and_(SourceCorpus.project_id == project_id, SourceDocument.status == "processed")
            )
            .order_by(SourceDocument.doc_id.asc())
        )
        return session.execute(stmt).scalars()

    def _iter_sentence_texts_for_doc(self, session: Session, doc_id: int) -> Iterable[str]:
        """Yield sentence texts for one document without ORM object hydration."""
        stmt = (
            select(DocumentSentence.text)
            .where(DocumentSentence.doc_id == doc_id)
            .order_by(DocumentSentence.sent_index.asc())
        )
        return session.execute(stmt).scalars()

    def _iter_sentence_rows_for_doc_ids(
        self,
        session: Session,
        doc_ids: list[int],
    ) -> Iterable[tuple[int, int, str, str | None, str | None]]:
        if not doc_ids:
            return []
        stmt = (
            select(
                DocumentSentence.doc_id,
                DocumentSentence.sentence_id,
                DocumentSentence.text,
                SentenceNLPSnapshot.payload_json,
                SentenceNLPSnapshot.sentence_text_hash,
            )
            .outerjoin(
                SentenceNLPSnapshot,
                SentenceNLPSnapshot.sentence_id == DocumentSentence.sentence_id,
            )
            .where(DocumentSentence.doc_id.in_([int(doc_id) for doc_id in doc_ids]))
            .order_by(DocumentSentence.doc_id.asc(), DocumentSentence.sent_index.asc())
        )
        return session.execute(stmt).all()

    def _load_sentence_nlp_sentences(
        self,
        *,
        sentence_id: int,
        sent_text: str,
        snapshot_payload_json: str | None,
        snapshot_text_hash: str | None,
        engine: NLPEngine,
    ) -> tuple[list, str]:
        expected_hash = build_sentence_text_hash(sent_text)
        if snapshot_payload_json and snapshot_text_hash == expected_hash:
            try:
                return deserialize_nlp_sentences(snapshot_payload_json), "snapshot"
            except Exception:
                logger.warning(
                    "Failed to decode sentence NLP snapshot for sentence_id=%s; falling back to reparse",
                    int(sentence_id),
                )
        elif snapshot_payload_json and snapshot_text_hash != expected_hash:
            logger.warning(
                "Ignoring stale sentence NLP snapshot for sentence_id=%s due to text hash mismatch",
                int(sentence_id),
            )

        return engine.process(sent_text), "fallback"

    def _collect_ngrams(
        self,
        session: Session,
        project_id: int,
        ngram_ns: tuple[int, ...],
        min_freq: int,
        summary: dict[str, int] | None = None,
    ) -> tuple[Counter, Counter, dict[tuple[str, int], dict[str, str]]]:
        """Collect n-gram counts from processed documents without writing."""
        logger.info(f"Extracting n-grams (sizes: {ngram_ns})")

        # Get project to check which engine was used
        project = session.get(DictProject, project_id)
        use_mock = project.nlp_engine.lower() == "mock" if project and project.nlp_engine else False

        # Get NLP engine for re-parsing sentences
        engine = self.get_nlp_engine(use_mock=use_mock)
        return self._collect_ngrams_for_doc_ids(
            session,
            [int(doc_id) for doc_id in self._iter_processed_doc_ids(session, project_id)],
            ngram_ns=ngram_ns,
            engine=engine,
            summary=summary,
        )

    def _collect_ngrams_for_doc_ids(
        self,
        session: Session,
        doc_ids: list[int],
        *,
        ngram_ns: tuple[int, ...],
        engine: NLPEngine,
        summary: dict[str, int] | None = None,
    ) -> tuple[Counter, Counter, dict[tuple[str, int], dict[str, str]]]:
        """Collect n-gram counts for a bounded list of docs."""
        ngram_counts = Counter()
        ngram_doc_freq = Counter()
        ngram_meta: dict[tuple[str, int], dict[str, str]] = {}

        if not doc_ids:
            return Counter(), Counter(), {}

        current_doc_id: int | None = None
        doc_ngrams_seen: set[tuple[str, int]] = set()
        snapshot_rows_used = 0
        fallback_rows_used = 0

        for (
            doc_id,
            sentence_id,
            sent_text,
            payload_json,
            snapshot_text_hash,
        ) in self._iter_sentence_rows_for_doc_ids(session, doc_ids):
            int_doc_id = int(doc_id)
            if current_doc_id != int_doc_id:
                current_doc_id = int_doc_id
                doc_ngrams_seen = set()

            nlp_sentences, source = self._load_sentence_nlp_sentences(
                sentence_id=int(sentence_id),
                sent_text=sent_text,
                snapshot_payload_json=payload_json,
                snapshot_text_hash=snapshot_text_hash,
                engine=engine,
            )
            if source == "snapshot":
                snapshot_rows_used += 1
            else:
                fallback_rows_used += 1
            if not nlp_sentences:
                continue

            for nlp_sent in nlp_sentences:
                tokens = [
                    {
                        "text": token.text,
                        "lemma": token.lemma,
                        "pos": token.pos,
                    }
                    for token in nlp_sent.tokens
                ]

                for ng in extract_ngrams_from_sentence(tokens, list(ngram_ns)):
                    key = (ng["surface_text"], ng["n"])
                    ngram_counts[key] += 1
                    if key not in doc_ngrams_seen:
                        ngram_doc_freq[key] += 1
                        doc_ngrams_seen.add(key)
                    if key not in ngram_meta:
                        ngram_meta[key] = {
                            "lemma_phrase": ng["lemma_phrase"],
                            "pos_pattern": ng["pos_pattern"],
                        }

        logger.info(
            "Collected n-grams for %d docs using %d sentence snapshots and %d reparsed sentences",
            len(doc_ids),
            snapshot_rows_used,
            fallback_rows_used,
        )
        if summary is not None:
            summary["snapshot_rows_used"] = (
                int(summary.get("snapshot_rows_used", 0)) + snapshot_rows_used
            )
            summary["reparsed_sentences"] = (
                int(summary.get("reparsed_sentences", 0)) + fallback_rows_used
            )
        return ngram_counts, ngram_doc_freq, ngram_meta

    def _build_lemma_freq_map(
        self,
        session: Session,
        project_id: int,
        lemma_texts: set[str],
    ) -> dict[str, int]:
        """Fetch required lemma frequencies once to avoid per-row lookups."""
        if not lemma_texts:
            return {}

        stmt = (
            select(Lemma.lemma_text, LemmaProjectStat.freq_abs)
            .join(
                LemmaProjectStat,
                and_(
                    LemmaProjectStat.lemma_id == Lemma.lemma_id,
                    LemmaProjectStat.project_id == Lemma.project_id,
                ),
            )
            .where(
                Lemma.project_id == project_id,
                Lemma.lemma_text.in_(sorted(lemma_texts)),
            )
        )
        return {
            str(lemma_text): int(freq_abs or 0)
            for lemma_text, freq_abs in session.execute(stmt).all()
        }

    def _store_ngrams(
        self,
        session: Session,
        project_id: int,
        *,
        ngram_counts: Counter,
        ngram_doc_freq: Counter,
        ngram_meta: dict[tuple[str, int], dict[str, str]],
        min_freq: int,
    ) -> int:
        """Store precomputed n-gram counters in one bounded write phase."""
        if not ngram_counts:
            return 0

        bigram_lemma_texts: set[str] = set()
        for (surface_text, n), freq in ngram_counts.items():
            if freq < min_freq:
                continue
            meta = ngram_meta.get((surface_text, n)) or {}
            if n != 2:
                continue
            lemmas = str(meta.get("lemma_phrase") or "").split()
            if len(lemmas) == 2:
                bigram_lemma_texts.update(lemmas)

        lemma_freq_map = self._build_lemma_freq_map(session, project_id, bigram_lemma_texts)
        total_tokens = self._get_total_tokens(session, project_id) if bigram_lemma_texts else 1

        ngrams_stored = 0
        for (surface_text, n), freq in ngram_counts.items():
            if freq < min_freq:
                continue

            meta = ngram_meta[(surface_text, n)]

            # Get canonical key
            canonical_key = get_cluster_key(surface_text, meta["lemma_phrase"])

            # Create Ngram
            ngram = Ngram(
                project_id=project_id,
                n=n,
                surface_text=surface_text,
                he_canonical=canonical_key,
                lemma_phrase=meta["lemma_phrase"],
                source_kind="ngram",
                pos_pattern=meta["pos_pattern"],
            )
            session.add(ngram)
            session.flush()  # Get ngram_id

            # Create NgramProjectStat with association measures
            doc_freq = ngram_doc_freq[(surface_text, n)]

            # Compute association measures (for bigrams)
            if n == 2:
                # Get component lemma counts
                lemmas = meta["lemma_phrase"].split()
                if len(lemmas) == 2:
                    l1, l2 = lemmas
                    c_x = lemma_freq_map.get(l1, 1)
                    c_y = lemma_freq_map.get(l2, 1)

                    measures = compute_all_measures(freq, c_x, c_y, total_tokens)
                else:
                    measures = {"pmi": None, "tscore": None, "llr": None, "dice": None}
            else:
                # Trigrams: compute simplified measures
                measures = {"pmi": None, "tscore": None, "llr": None, "dice": None}

            stat = NgramProjectStat(
                project_id=project_id,
                ngram_id=ngram.ngram_id,
                freq_abs=freq,
                doc_freq=doc_freq,
                pmi_cache=measures["pmi"],
                tscore_cache=measures["tscore"],
                llr_cache=measures["llr"],
                dice_cache=measures["dice"],
            )
            session.add(stat)

            ngrams_stored += 1

        session.flush()
        logger.info(f"Stored {ngrams_stored} n-grams (min_freq={min_freq})")
        return ngrams_stored

    def _extract_ngrams(
        self, session: Session, project_id: int, ngram_ns: tuple[int, ...], min_freq: int
    ) -> int:
        """Compatibility wrapper for tests/older callers."""
        ngram_counts, ngram_doc_freq, ngram_meta = self._collect_ngrams(
            session, project_id, ngram_ns, min_freq
        )
        return self._store_ngrams(
            session,
            project_id,
            ngram_counts=ngram_counts,
            ngram_doc_freq=ngram_doc_freq,
            ngram_meta=ngram_meta,
            min_freq=min_freq,
        )

    def _collect_np_chunks(
        self,
        session: Session,
        project_id: int,
        np_max_len: int,
        min_freq: int,
        summary: dict[str, int] | None = None,
    ) -> tuple[Counter, Counter, dict[tuple[str, int], dict[str, str]]]:
        """Collect NP chunks from processed documents without writing."""
        logger.info(f"Extracting NP chunks (max_len={np_max_len})")

        # Get project to check which engine was used
        project = session.get(DictProject, project_id)
        use_mock = project.nlp_engine.lower() == "mock" if project and project.nlp_engine else False

        # Get NLP engine for re-parsing sentences
        engine = self.get_nlp_engine(use_mock=use_mock)
        return self._collect_np_chunks_for_doc_ids(
            session,
            [int(doc_id) for doc_id in self._iter_processed_doc_ids(session, project_id)],
            np_max_len=np_max_len,
            engine=engine,
            summary=summary,
        )

    def _collect_np_chunks_for_doc_ids(
        self,
        session: Session,
        doc_ids: list[int],
        *,
        np_max_len: int,
        engine: NLPEngine,
        summary: dict[str, int] | None = None,
    ) -> tuple[Counter, Counter, dict[tuple[str, int], dict[str, str]]]:
        """Collect NP chunk counts for a bounded list of docs."""
        np_counts = Counter()
        np_doc_freq = Counter()
        np_meta: dict[tuple[str, int], dict[str, str]] = {}

        if not doc_ids:
            return Counter(), Counter(), {}

        current_doc_id: int | None = None
        doc_nps_seen: set[tuple[str, int]] = set()
        snapshot_rows_used = 0
        fallback_rows_used = 0

        for (
            doc_id,
            sentence_id,
            sent_text,
            payload_json,
            snapshot_text_hash,
        ) in self._iter_sentence_rows_for_doc_ids(session, doc_ids):
            int_doc_id = int(doc_id)
            if current_doc_id != int_doc_id:
                current_doc_id = int_doc_id
                doc_nps_seen = set()

            nlp_sentences, source = self._load_sentence_nlp_sentences(
                sentence_id=int(sentence_id),
                sent_text=sent_text,
                snapshot_payload_json=payload_json,
                snapshot_text_hash=snapshot_text_hash,
                engine=engine,
            )
            if source == "snapshot":
                snapshot_rows_used += 1
            else:
                fallback_rows_used += 1
            if not nlp_sentences:
                continue

            for nlp_sent in nlp_sentences:
                tokens = [
                    {
                        "text": token.text,
                        "lemma": token.lemma,
                        "pos": token.pos,
                    }
                    for token in nlp_sent.tokens
                ]

                for np in extract_np_chunks_from_sentence(tokens, min_len=2, max_len=np_max_len):
                    key = (np["surface_text"], np["n"])
                    np_counts[key] += 1
                    if key not in doc_nps_seen:
                        np_doc_freq[key] += 1
                        doc_nps_seen.add(key)
                    if key not in np_meta:
                        np_meta[key] = {
                            "lemma_phrase": np["lemma_phrase"],
                            "pos_pattern": np["pos_pattern"],
                        }

        logger.info(
            "Collected NP chunks for %d docs using %d sentence snapshots and %d reparsed sentences",
            len(doc_ids),
            snapshot_rows_used,
            fallback_rows_used,
        )
        if summary is not None:
            summary["snapshot_rows_used"] = (
                int(summary.get("snapshot_rows_used", 0)) + snapshot_rows_used
            )
            summary["reparsed_sentences"] = (
                int(summary.get("reparsed_sentences", 0)) + fallback_rows_used
            )
        return np_counts, np_doc_freq, np_meta

    def _store_np_chunks(
        self,
        session: Session,
        project_id: int,
        *,
        np_counts: Counter,
        np_doc_freq: Counter,
        np_meta: dict[tuple[str, int], dict[str, str]],
        min_freq: int,
    ) -> int:
        """Store precomputed NP counters in one bounded write phase."""
        if not np_counts:
            return 0

        nps_stored = 0
        for (surface_text, n), freq in np_counts.items():
            if freq < min_freq:
                continue

            meta = np_meta[(surface_text, n)]

            # Get canonical key
            canonical_key = get_cluster_key(surface_text, meta["lemma_phrase"])

            # Create Ngram with source_kind='np'
            ngram = Ngram(
                project_id=project_id,
                n=n,
                surface_text=surface_text,
                he_canonical=canonical_key,
                lemma_phrase=meta["lemma_phrase"],
                source_kind="np",
                pos_pattern=meta["pos_pattern"],
            )
            session.add(ngram)
            session.flush()  # Get ngram_id

            # Create NgramProjectStat (no association measures for NPs)
            doc_freq = np_doc_freq[(surface_text, n)]

            stat = NgramProjectStat(
                project_id=project_id,
                ngram_id=ngram.ngram_id,
                freq_abs=freq,
                doc_freq=doc_freq,
                pmi_cache=None,  # Not computed for NP chunks
                tscore_cache=None,
                llr_cache=None,
                dice_cache=None,
            )
            session.add(stat)

            nps_stored += 1

        session.flush()
        logger.info(f"Stored {nps_stored} NP chunks (min_freq={min_freq})")
        return nps_stored

    def _extract_np_chunks(
        self, session: Session, project_id: int, np_max_len: int, min_freq: int
    ) -> int:
        """Compatibility wrapper for tests/older callers."""
        np_counts, np_doc_freq, np_meta = self._collect_np_chunks(
            session, project_id, np_max_len, min_freq
        )
        return self._store_np_chunks(
            session,
            project_id,
            np_counts=np_counts,
            np_doc_freq=np_doc_freq,
            np_meta=np_meta,
            min_freq=min_freq,
        )

    def _upsert_term_extract_accumulators(
        self,
        session: Session,
        *,
        run_id: int,
        source_kind: str,
        counts: Counter,
        doc_freq: Counter,
        meta: dict[tuple[str, int], dict[str, str]],
        insert_batch_size: int = 200,
    ) -> int:
        """Upsert staged term counters for one collected batch."""
        if not counts:
            return 0

        rows = []
        for (surface_text, n), freq_abs in counts.items():
            meta_row = meta.get((surface_text, n)) or {}
            rows.append(
                {
                    "run_id": int(run_id),
                    "source_kind": source_kind,
                    "n": int(n),
                    "surface_text": str(surface_text),
                    "lemma_phrase": meta_row.get("lemma_phrase"),
                    "pos_pattern": meta_row.get("pos_pattern"),
                    "freq_abs": int(freq_abs or 0),
                    "doc_freq": int(doc_freq.get((surface_text, n), 0) or 0),
                    "updated_at": self._utc_now(),
                }
            )

        inserted = 0
        for start in range(0, len(rows), insert_batch_size):
            chunk = rows[start : start + insert_batch_size]
            stmt = sqlite_insert(TermExtractAccumulator.__table__).values(chunk)
            excluded = stmt.excluded
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    "run_id",
                    "source_kind",
                    "n",
                    "surface_text",
                ],
                set_={
                    "freq_abs": TermExtractAccumulator.freq_abs + excluded.freq_abs,
                    "doc_freq": TermExtractAccumulator.doc_freq + excluded.doc_freq,
                    "lemma_phrase": func.coalesce(
                        func.nullif(TermExtractAccumulator.lemma_phrase, ""),
                        excluded.lemma_phrase,
                    ),
                    "pos_pattern": func.coalesce(
                        func.nullif(TermExtractAccumulator.pos_pattern, ""),
                        excluded.pos_pattern,
                    ),
                    "updated_at": excluded.updated_at,
                },
            )
            session.execute(stmt)
            inserted += len(chunk)

        session.flush()
        return inserted

    def _iter_term_extract_accumulator_batches(
        self,
        session: Session,
        *,
        run_id: int,
        source_kind: str,
        min_freq: int,
        batch_size: int = 500,
    ) -> Iterable[list[dict]]:
        """Yield staged accumulator rows in deterministic bounded batches."""
        last_n: int | None = None
        last_surface: str | None = None

        while True:
            stmt = (
                select(
                    TermExtractAccumulator.n,
                    TermExtractAccumulator.surface_text,
                    TermExtractAccumulator.lemma_phrase,
                    TermExtractAccumulator.pos_pattern,
                    TermExtractAccumulator.freq_abs,
                    TermExtractAccumulator.doc_freq,
                )
                .where(
                    and_(
                        TermExtractAccumulator.run_id == run_id,
                        TermExtractAccumulator.source_kind == source_kind,
                        TermExtractAccumulator.freq_abs >= int(min_freq),
                    )
                )
                .order_by(TermExtractAccumulator.n.asc(), TermExtractAccumulator.surface_text.asc())
                .limit(int(batch_size))
            )
            if last_n is not None and last_surface is not None:
                stmt = stmt.where(
                    or_(
                        TermExtractAccumulator.n > last_n,
                        and_(
                            TermExtractAccumulator.n == last_n,
                            TermExtractAccumulator.surface_text > last_surface,
                        ),
                    )
                )

            rows = [dict(row) for row in session.execute(stmt).mappings().all()]
            if not rows:
                return

            yield rows
            last_n = int(rows[-1]["n"])
            last_surface = str(rows[-1]["surface_text"])

    def _store_staged_ngrams(
        self,
        session: Session,
        project_id: int,
        *,
        run_id: int,
        min_freq: int,
        total_tokens: int,
        progress_callback: Callable[[str], None] | None = None,
    ) -> int:
        """Store staged ngram accumulators into final term tables."""
        ngrams_stored = 0
        batch_no = 0
        for rows in self._iter_term_extract_accumulator_batches(
            session,
            run_id=run_id,
            source_kind="ngram",
            min_freq=min_freq,
        ):
            batch_no += 1
            bigram_lemma_texts: set[str] = set()
            for row in rows:
                if int(row["n"]) != 2:
                    continue
                lemmas = str(row.get("lemma_phrase") or "").split()
                if len(lemmas) == 2:
                    bigram_lemma_texts.update(lemmas)
            lemma_freq_map = self._build_lemma_freq_map(session, project_id, bigram_lemma_texts)

            for row in rows:
                n = int(row["n"])
                surface_text = str(row["surface_text"])
                lemma_phrase = str(row.get("lemma_phrase") or "")
                pos_pattern = row.get("pos_pattern")
                freq_abs = int(row["freq_abs"] or 0)
                doc_freq = int(row["doc_freq"] or 0)

                canonical_key = get_cluster_key(surface_text, lemma_phrase)
                ngram_result = session.execute(
                    Ngram.__table__.insert().values(
                        project_id=project_id,
                        n=n,
                        surface_text=surface_text,
                        he_canonical=canonical_key,
                        lemma_phrase=lemma_phrase,
                        source_kind="ngram",
                        pos_pattern=pos_pattern,
                    )
                )
                ngram_id = int(ngram_result.inserted_primary_key[0])

                if n == 2:
                    lemmas = lemma_phrase.split()
                    if len(lemmas) == 2:
                        l1, l2 = lemmas
                        measures = compute_all_measures(
                            freq_abs,
                            lemma_freq_map.get(l1, 1),
                            lemma_freq_map.get(l2, 1),
                            int(total_tokens or 1),
                        )
                    else:
                        measures = {"pmi": None, "tscore": None, "llr": None, "dice": None}
                else:
                    measures = {"pmi": None, "tscore": None, "llr": None, "dice": None}

                session.execute(
                    NgramProjectStat.__table__.insert().values(
                        project_id=project_id,
                        ngram_id=ngram_id,
                        freq_abs=freq_abs,
                        doc_freq=doc_freq,
                        pmi_cache=measures["pmi"],
                        tscore_cache=measures["tscore"],
                        llr_cache=measures["llr"],
                        dice_cache=measures["dice"],
                    )
                )
                ngrams_stored += 1

            session.flush()
            if progress_callback:
                progress_callback(f"Stored n-gram batch {batch_no} ({ngrams_stored} total)")

        return ngrams_stored

    def _store_staged_np_chunks(
        self,
        session: Session,
        project_id: int,
        *,
        run_id: int,
        min_freq: int,
        progress_callback: Callable[[str], None] | None = None,
    ) -> int:
        """Store staged NP accumulators into final term tables."""
        nps_stored = 0
        batch_no = 0
        for rows in self._iter_term_extract_accumulator_batches(
            session,
            run_id=run_id,
            source_kind="np",
            min_freq=min_freq,
        ):
            batch_no += 1
            for row in rows:
                ngram_result = session.execute(
                    Ngram.__table__.insert().values(
                        project_id=project_id,
                        n=int(row["n"]),
                        surface_text=str(row["surface_text"]),
                        he_canonical=get_cluster_key(
                            str(row["surface_text"]),
                            str(row.get("lemma_phrase") or ""),
                        ),
                        lemma_phrase=str(row.get("lemma_phrase") or ""),
                        source_kind="np",
                        pos_pattern=row.get("pos_pattern"),
                    )
                )
                ngram_id = int(ngram_result.inserted_primary_key[0])
                session.execute(
                    NgramProjectStat.__table__.insert().values(
                        project_id=project_id,
                        ngram_id=ngram_id,
                        freq_abs=int(row["freq_abs"] or 0),
                        doc_freq=int(row["doc_freq"] or 0),
                        pmi_cache=None,
                        tscore_cache=None,
                        llr_cache=None,
                        dice_cache=None,
                    )
                )
                nps_stored += 1

            session.flush()
            if progress_callback:
                progress_callback(f"Stored NP batch {batch_no} ({nps_stored} total)")

        return nps_stored

    def _ensure_cluster_canonical_keys(self, session: Session, project_id: int) -> int:
        """Backfill missing canonical keys so clustering can stream deterministically."""
        stmt = (
            select(Ngram.ngram_id, Ngram.surface_text, Ngram.lemma_phrase)
            .where(
                and_(
                    Ngram.project_id == project_id,
                    or_(Ngram.he_canonical.is_(None), Ngram.he_canonical == ""),
                )
            )
            .order_by(Ngram.ngram_id.asc())
        )
        updates = []
        for ngram_id, surface_text, lemma_phrase in session.execute(stmt):
            updates.append(
                {
                    "u_ngram_id": int(ngram_id),
                    "u_he_canonical": get_cluster_key(surface_text, lemma_phrase),
                }
            )

        if not updates:
            return 0

        update_stmt = (
            Ngram.__table__.update()
            .where(Ngram.ngram_id == bindparam("u_ngram_id"))
            .values(he_canonical=bindparam("u_he_canonical"))
        )
        session.execute(update_stmt, updates)
        session.flush()
        logger.info("Backfilled %d missing ngram canonical keys", len(updates))
        return len(updates)

    def _iter_cluster_key_batches(
        self,
        session: Session,
        project_id: int,
        *,
        batch_size: int = 500,
    ) -> Iterable[list[str]]:
        """Yield canonical keys in deterministic batches for bounded clustering."""
        last_key: str | None = None
        while True:
            stmt = (
                select(Ngram.he_canonical)
                .where(
                    and_(
                        Ngram.project_id == project_id,
                        Ngram.he_canonical.is_not(None),
                        Ngram.he_canonical != "",
                    )
                )
                .distinct()
                .order_by(Ngram.he_canonical.asc())
                .limit(batch_size)
            )
            if last_key is not None:
                stmt = stmt.where(Ngram.he_canonical > last_key)

            canonical_keys = [str(value) for value in session.execute(stmt).scalars().all()]
            if not canonical_keys:
                return

            yield canonical_keys
            last_key = canonical_keys[-1]

    def _insert_cluster_from_members(
        self,
        session: Session,
        project_id: int,
        canonical_key: str,
        members: list[dict],
        classification_stats: dict,
    ) -> int:
        """Insert one cluster and its members from pre-fetched member rows."""
        if not members:
            return 0

        total_freq = sum(int(member["freq_abs"] or 0) for member in members)
        total_doc_freq = max(int(member["doc_freq"] or 0) for member in members)

        pmis = [member["pmi_cache"] for member in members if member["pmi_cache"] is not None]
        llrs = [member["llr_cache"] for member in members if member["llr_cache"] is not None]
        dices = [member["dice_cache"] for member in members if member["dice_cache"] is not None]
        tscores = [
            member["tscore_cache"] for member in members if member["tscore_cache"] is not None
        ]

        terms_for_rep = [
            {"surface_text": str(member["surface_text"]), "freq_abs": int(member["freq_abs"] or 0)}
            for member in members
        ]
        representative_he = choose_representative_term(terms_for_rep)
        representative_lemma = next(
            (str(member["lemma_phrase"]) for member in members if member["lemma_phrase"]),
            None,
        )
        source_kinds = sorted(
            {str(member["source_kind"]) for member in members if member["source_kind"]}
        )

        classification = classify_phrase(representative_he)
        classification_stats["classes"][classification.entity_class] += 1
        if classification.is_noise:
            classification_stats["noise"] += 1

        cluster_result = session.execute(
            TermCluster.__table__.insert().values(
                project_id=project_id,
                canonical_key=canonical_key,
                representative_he=representative_he,
                representative_lemma=representative_lemma,
                freq_abs=total_freq,
                doc_freq=total_doc_freq,
                members_count=len(members),
                best_pmi=max(pmis) if pmis else None,
                best_llr=max(llrs) if llrs else None,
                best_dice=max(dices) if dices else None,
                best_tscore=max(tscores) if tscores else None,
                source_kinds=",".join(source_kinds) if source_kinds else None,
                entity_class=classification.entity_class,
                is_noise=1 if classification.is_noise else 0,
                noise_reason=classification.noise_reason,
                norm_text=classification.norm_text,
            )
        )
        cluster_id = int(cluster_result.inserted_primary_key[0])

        session.execute(
            TermClusterMember.__table__.insert(),
            [
                {
                    "cluster_id": cluster_id,
                    "ngram_id": int(member["ngram_id"]),
                    "member_freq_abs": int(member["freq_abs"] or 0),
                    "member_doc_freq": int(member["doc_freq"] or 0),
                }
                for member in members
            ],
        )
        return 1

    def _cluster_terms(self, session: Session, project_id: int) -> int:
        """
        Cluster terms by canonical key (M5.1).

        Returns:
            Number of clusters created
        """
        logger.info("Clustering terms by canonical key")

        self._ensure_cluster_canonical_keys(session, project_id)

        clusters_created = 0
        classification_stats = {"noise": 0, "classes": Counter()}

        for canonical_keys in self._iter_cluster_key_batches(session, project_id):
            stmt = (
                select(
                    Ngram.ngram_id.label("ngram_id"),
                    Ngram.surface_text.label("surface_text"),
                    Ngram.lemma_phrase.label("lemma_phrase"),
                    Ngram.he_canonical.label("he_canonical"),
                    Ngram.source_kind.label("source_kind"),
                    NgramProjectStat.freq_abs.label("freq_abs"),
                    NgramProjectStat.doc_freq.label("doc_freq"),
                    NgramProjectStat.pmi_cache.label("pmi_cache"),
                    NgramProjectStat.llr_cache.label("llr_cache"),
                    NgramProjectStat.dice_cache.label("dice_cache"),
                    NgramProjectStat.tscore_cache.label("tscore_cache"),
                )
                .join(
                    NgramProjectStat,
                    and_(
                        NgramProjectStat.ngram_id == Ngram.ngram_id,
                        NgramProjectStat.project_id == Ngram.project_id,
                    ),
                )
                .where(
                    and_(
                        Ngram.project_id == project_id,
                        Ngram.he_canonical.in_(canonical_keys),
                    )
                )
                .order_by(Ngram.he_canonical.asc(), Ngram.ngram_id.asc())
            )
            rows = [dict(row) for row in session.execute(stmt).mappings()]

            current_key: str | None = None
            current_members: list[dict] = []
            for row in rows:
                canonical_key = str(row["he_canonical"])
                if current_key is None:
                    current_key = canonical_key
                if canonical_key != current_key:
                    clusters_created += self._insert_cluster_from_members(
                        session,
                        project_id,
                        current_key,
                        current_members,
                        classification_stats,
                    )
                    current_members = []
                    current_key = canonical_key
                current_members.append(row)

            if current_key is not None and current_members:
                clusters_created += self._insert_cluster_from_members(
                    session,
                    project_id,
                    current_key,
                    current_members,
                    classification_stats,
                )

        session.flush()

        # Log classification summary
        logger.info(
            f"Created {clusters_created} clusters ({classification_stats['noise']} noise, "
            f"{clusters_created - classification_stats['noise']} valid). "
            f"Classes: {dict(classification_stats['classes'])}"
        )

        return clusters_created

    def _get_lemma_freq(self, session: Session, project_id: int, lemma_text: str) -> int:
        """Get total frequency of a lemma."""
        from app.infra.sa_models import Lemma, LemmaProjectStat

        stmt = (
            select(LemmaProjectStat.freq_abs)
            .join(Lemma)
            .where(and_(Lemma.project_id == project_id, Lemma.lemma_text == lemma_text))
        )
        result = session.execute(stmt).scalar()
        return result or 1  # Avoid division by zero

    def _get_total_tokens(self, session: Session, project_id: int) -> int:
        """Get total token count for project."""
        from app.infra.sa_models import LemmaProjectStat

        stmt = select(func.sum(LemmaProjectStat.freq_abs)).where(
            LemmaProjectStat.project_id == project_id
        )
        result = session.execute(stmt).scalar()
        return result or 1  # Avoid division by zero

    def list_term_clusters(
        self,
        session: Session,
        project_id: int,
        *,
        top_n: int = 500,
        search: str | None = None,
        preset: str = "freq",
        min_freq: int | None = None,
        source_filter: str | None = None,
        hide_noise: bool = True,
        offset: int = 0,
    ) -> list[ClusterStats]:
        """
        List term clusters with filtering and ranking.

        Args:
            session: DB session
            project_id: Project ID
            top_n: Limit results
            search: Search term (LIKE)
            preset: Ranking preset ('freq', 'strong', 'balanced', 'termhood')
            min_freq: Minimum frequency filter
            source_filter: Source kind filter ('ngram', 'np', or None for all)
            hide_noise: Hide noisy clusters (default True, Task 11)

        Returns:
            List of ClusterStats
        """
        # M5.4: Termhood preset requires reference corpus
        if preset == "termhood":
            reference_project_id = self.get_reference_project(session, project_id)
            if reference_project_id:
                return self._list_clusters_with_termhood(
                    session,
                    project_id,
                    reference_project_id,
                    top_n=top_n,
                    search=search,
                    min_freq=min_freq,
                    source_filter=source_filter,
                )
            else:
                # No reference set - fall back to freq preset
                logger.warning(
                    f"Termhood preset requested but no reference project set for {project_id}"
                )
                preset = "freq"
        stmt = select(TermCluster).where(TermCluster.project_id == project_id)

        # Filter by source kind if specified (M5.3)
        if source_filter:
            # Join with members to filter by source_kind
            stmt = (
                stmt.join(TermClusterMember)
                .join(Ngram)
                .where(Ngram.source_kind == source_filter)
                .distinct()
            )

        # Apply filters
        if min_freq:
            stmt = stmt.where(TermCluster.freq_abs >= min_freq)

        # Apply noise filter (Task 11: Entity Classification)
        if hide_noise:
            # Hide noise: is_noise = 0 OR is_noise IS NULL (backward compatibility)
            stmt = stmt.where(or_(TermCluster.is_noise == 0, TermCluster.is_noise.is_(None)))

        if search:
            # Generate normalized search variants (handles articles, spaces, etc.)
            search_variants = normalize_search_query(search)

            if search_variants:
                # Build OR clause across multiple fields and variants
                search_conditions = []

                for variant in search_variants:
                    # Match against representative Hebrew term (display)
                    search_conditions.append(TermCluster.representative_he.contains(variant))

                    # Match against canonical key (normalized form)
                    search_conditions.append(TermCluster.canonical_key.contains(variant))

                    # Match against representative lemma (normalized lemma)
                    if TermCluster.representative_lemma is not None:
                        search_conditions.append(TermCluster.representative_lemma.contains(variant))

                # Combine with OR (match any variant in any field)
                stmt = stmt.where(or_(*search_conditions))
            else:
                # Fallback: original behavior if normalization fails
                stmt = stmt.where(TermCluster.representative_he.contains(search))

        # Apply ranking preset
        if preset == "freq":
            stmt = stmt.order_by(
                TermCluster.freq_abs.desc(),
                TermCluster.doc_freq.desc(),
                TermCluster.best_pmi.desc(),
            )
        elif preset == "strong":
            stmt = stmt.where(TermCluster.freq_abs >= 2).order_by(
                TermCluster.best_llr.desc(), TermCluster.best_pmi.desc()
            )
        elif preset == "balanced":
            # M5.2: Balanced ranking using multiple signals
            stmt = stmt.order_by(
                TermCluster.best_llr.desc(),
                TermCluster.best_dice.desc(),
                TermCluster.doc_freq.desc(),
                TermCluster.freq_abs.desc(),
            )

        stmt = stmt.limit(top_n).offset(offset)

        clusters = session.execute(stmt).scalars().all()

        # Convert to DTOs
        results = []
        for c in clusters:
            results.append(
                ClusterStats(
                    cluster_id=c.cluster_id,
                    canonical_key=c.canonical_key,
                    representative_he=c.representative_he,
                    representative_lemma=c.representative_lemma,
                    freq_abs=c.freq_abs,
                    doc_freq=c.doc_freq,
                    members_count=c.members_count,
                    best_pmi=c.best_pmi,
                    best_llr=c.best_llr,
                    best_dice=c.best_dice,
                    best_tscore=c.best_tscore,
                    entity_class=c.entity_class,
                    is_noise=c.is_noise,
                    noise_reason=c.noise_reason,
                    norm_text=c.norm_text,
                )
            )

        return results

    def count_term_clusters(
        self,
        session: Session,
        project_id: int,
        *,
        search: str | None = None,
        min_freq: int | None = None,
        source_filter: str | None = None,
        hide_noise: bool = True,
    ) -> int:
        """
        Count total term clusters matching filters (for pagination).

        Args:
            session: Database session
            project_id: Project ID
            search: Search text (optional)
            min_freq: Minimum frequency filter
            source_filter: Source kind filter ("ngrams" or "np")
            hide_noise: Hide noise clusters (default True)

        Returns:
            Total count of matching clusters
        """
        stmt = (
            select(func.count())
            .select_from(TermCluster)
            .where(TermCluster.project_id == project_id)
        )

        # Apply same filters as list_term_clusters (but no limit/offset)
        # Source filter
        if source_filter:
            stmt = (
                stmt.join(TermClusterMember)
                .join(Ngram)
                .where(Ngram.source_kind == source_filter)
                .distinct()
            )

        # Min freq filter
        if min_freq:
            stmt = stmt.where(TermCluster.freq_abs >= min_freq)

        # Noise filter
        if hide_noise:
            stmt = stmt.where(or_(TermCluster.is_noise == 0, TermCluster.is_noise.is_(None)))

        # Search filter with normalized variants
        if search:
            search_norm = search.replace(" ", "_").lower()
            stmt = stmt.where(
                or_(
                    TermCluster.representative_he.contains(search),
                    TermCluster.norm_text.contains(search_norm),
                )
            )

        count = session.execute(stmt).scalar()
        return count or 0

    def count_cluster_ids_for_translation(
        self,
        session: Session,
        project_id: int,
        filters: dict,
        write_mode: str,
    ) -> int:
        """Count term clusters matching filters for translation.

        Filters by empty translation if write_mode is FILL_EMPTY or SKIP_NON_EMPTY.

        Args:
            session: Database session
            project_id: Project ID
            filters: Filter dict with keys: search, min_freq, source_filter, hide_noise, preset
            write_mode: "FILL_EMPTY" | "SKIP_NON_EMPTY" | "OVERWRITE"

        Returns:
            Total count of clusters to translate
        """
        stmt = (
            select(func.count(TermCluster.cluster_id.distinct()))
            .select_from(TermCluster)
            .where(TermCluster.project_id == project_id)
        )

        # Apply filters (mirror list_term_clusters logic)
        source_filter = filters.get("source_filter")
        if source_filter:
            stmt = (
                stmt.join(TermClusterMember)
                .join(Ngram)
                .where(Ngram.source_kind == source_filter)
                .distinct()
            )

        min_freq = filters.get("min_freq")
        if min_freq:
            stmt = stmt.where(TermCluster.freq_abs >= min_freq)

        if filters.get("hide_noise", True):
            stmt = stmt.where(or_(TermCluster.is_noise == 0, TermCluster.is_noise.is_(None)))

        search = filters.get("search", "").strip()
        if search:
            search_variants = normalize_search_query(search)
            if search_variants:
                search_conditions = []
                for variant in search_variants:
                    search_conditions.append(TermCluster.representative_he.contains(variant))
                    search_conditions.append(TermCluster.canonical_key.contains(variant))
                    if TermCluster.representative_lemma is not None:
                        search_conditions.append(TermCluster.representative_lemma.contains(variant))
                stmt = stmt.where(or_(*search_conditions))
            else:
                stmt = stmt.where(TermCluster.representative_he.contains(search))

        # For FILL_EMPTY and SKIP_NON_EMPTY: only count clusters without translation
        if write_mode in ("FILL_EMPTY", "SKIP_NON_EMPTY"):
            stmt = stmt.outerjoin(
                TMEntry,
                (TMEntry.cluster_id == TermCluster.cluster_id)
                & (TMEntry.kind == "term_cluster")
                & (TMEntry.project_id == project_id),
            ).where(
                or_(
                    TMEntry.tm_id.is_(None),
                    TMEntry.translation.is_(None),
                    TMEntry.translation == "",
                )
            )

        count = session.execute(stmt).scalar()
        return count or 0

    def fetch_cluster_ids_for_translation(
        self,
        session: Session,
        project_id: int,
        filters: dict,
        write_mode: str,
        limit: int,
        offset: int,
    ) -> list[int]:
        """Fetch term cluster IDs matching filters for translation (paginated).

        Args:
            session: Database session
            project_id: Project ID
            filters: Filter dict (same as count_cluster_ids_for_translation)
            write_mode: "FILL_EMPTY" | "SKIP_NON_EMPTY" | "OVERWRITE"
            limit: Chunk size
            offset: Offset for pagination

        Returns:
            List of cluster_id integers
        """
        stmt = select(TermCluster.cluster_id).where(TermCluster.project_id == project_id)

        # Apply filters (mirror list_term_clusters logic)
        source_filter = filters.get("source_filter")
        if source_filter:
            stmt = (
                stmt.join(TermClusterMember)
                .join(Ngram)
                .where(Ngram.source_kind == source_filter)
                .distinct()
            )

        min_freq = filters.get("min_freq")
        if min_freq:
            stmt = stmt.where(TermCluster.freq_abs >= min_freq)

        if filters.get("hide_noise", True):
            stmt = stmt.where(or_(TermCluster.is_noise == 0, TermCluster.is_noise.is_(None)))

        search = filters.get("search", "").strip()
        if search:
            search_variants = normalize_search_query(search)
            if search_variants:
                search_conditions = []
                for variant in search_variants:
                    search_conditions.append(TermCluster.representative_he.contains(variant))
                    search_conditions.append(TermCluster.canonical_key.contains(variant))
                    if TermCluster.representative_lemma is not None:
                        search_conditions.append(TermCluster.representative_lemma.contains(variant))
                stmt = stmt.where(or_(*search_conditions))
            else:
                stmt = stmt.where(TermCluster.representative_he.contains(search))

        # For FILL_EMPTY and SKIP_NON_EMPTY: only fetch clusters without translation
        if write_mode in ("FILL_EMPTY", "SKIP_NON_EMPTY"):
            stmt = stmt.outerjoin(
                TMEntry,
                (TMEntry.cluster_id == TermCluster.cluster_id)
                & (TMEntry.kind == "term_cluster")
                & (TMEntry.project_id == project_id),
            ).where(
                or_(
                    TMEntry.tm_id.is_(None),
                    TMEntry.translation.is_(None),
                    TMEntry.translation == "",
                )
            )

        # Order by cluster_id for deterministic chunking
        stmt = stmt.order_by(TermCluster.cluster_id.asc())

        # Apply pagination
        stmt = stmt.limit(limit).offset(offset)

        results = session.execute(stmt).scalars().all()
        return list(results)

    def get_cluster_members(self, session: Session, cluster_id: int) -> list[dict]:
        """
        Get cluster members (surface variants).

        Returns:
            List of dicts with ngram details
        """
        stmt = (
            select(Ngram, NgramProjectStat, TermClusterMember)
            .join(TermClusterMember, Ngram.ngram_id == TermClusterMember.ngram_id)
            .join(
                NgramProjectStat,
                and_(
                    NgramProjectStat.ngram_id == Ngram.ngram_id,
                    NgramProjectStat.project_id == Ngram.project_id,
                ),
            )
            .where(TermClusterMember.cluster_id == cluster_id)
        )

        results = session.execute(stmt).all()

        members = []
        for ngram, stat, member in results:
            members.append(
                {
                    "surface_text": ngram.surface_text,
                    "lemma_phrase": ngram.lemma_phrase,
                    "freq_abs": stat.freq_abs,
                    "doc_freq": stat.doc_freq,
                    "pmi": stat.pmi_cache,
                    "llr": stat.llr_cache,
                }
            )

        return members

    # ===================================================================
    # M5.4: Termhood vs Reference Corpus
    # ===================================================================

    def set_reference_project(
        self, session: Session, project_id: int, reference_project_id: int | None
    ) -> None:
        """
        Set the reference (general) corpus for termhood comparison.

        Args:
            session: DB session
            project_id: Domain project ID
            reference_project_id: Reference project ID (or None to clear)
        """
        project = session.get(DictProject, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        project.general_corpus_id = reference_project_id
        from app.infra.db_retry import with_retry_on_locked

        with_retry_on_locked(
            session.commit,
            max_retries=4,
            rollback_callback=session.rollback,
        )
        logger.info(f"Set reference project for {project_id}: {reference_project_id}")

    def get_reference_project(self, session: Session, project_id: int) -> int | None:
        """
        Get the reference (general) corpus ID for a project.

        Args:
            session: DB session
            project_id: Project ID

        Returns:
            Reference project ID or None
        """
        project = session.get(DictProject, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        return project.general_corpus_id

    def _get_default_reference_corpus_id(self, session: Session) -> int | None:
        """
        Get the default reference corpus ID (is_general_corpus=1).

        Args:
            session: DB session

        Returns:
            Default reference corpus ID or None if not found
        """
        stmt = select(DictProject.project_id).where(DictProject.is_general_corpus == 1)
        result = session.execute(stmt).scalar_one_or_none()
        return result

    def list_projects(self, session: Session) -> list[tuple[int, str]]:
        """
        List all projects for reference selection.

        Args:
            session: DB session

        Returns:
            List of (project_id, name) tuples
        """
        stmt = select(DictProject.project_id, DictProject.name).order_by(DictProject.name)
        results = session.execute(stmt).all()
        return [(r[0], r[1]) for r in results]

    def _get_total_cluster_tokens(self, session: Session, project_id: int) -> int:
        """
        Get total tokens in all clusters for a project (N_d or N_r).

        This is the sum of freq_abs across all clusters.

        Args:
            session: DB session
            project_id: Project ID

        Returns:
            Total cluster token count
        """
        stmt = select(func.sum(TermCluster.freq_abs)).where(TermCluster.project_id == project_id)
        result = session.execute(stmt).scalar()
        return result or 0

    def _compute_weirdness(self, f_d: int, N_d: int, f_r: int, N_r: int) -> float:
        """
        Compute weirdness ratio with smoothing.

        Weirdness = (f_d / N_d) / (f_r / N_r)

        High weirdness (> 1.0) indicates term is more frequent in domain vs reference.

        Args:
            f_d: Cluster frequency in domain
            N_d: Total cluster tokens in domain
            f_r: Cluster frequency in reference
            N_r: Total cluster tokens in reference

        Returns:
            Weirdness ratio
        """
        # Smoothing to avoid division by zero
        f_d_s = f_d + 0.5
        f_r_s = f_r + 0.5
        N_d_s = N_d + 1.0
        N_r_s = N_r + 1.0

        weirdness = (f_d_s / N_d_s) / (f_r_s / N_r_s)
        return weirdness

    def _compute_keyness_llr(self, f_d: int, N_d: int, f_r: int, N_r: int) -> float:
        """
        Compute keyness using log-likelihood ratio (2x2 contingency table).

        Contingency table:
                   | Domain | Reference |
        -----------|--------|-----------|
        Term       |   a    |     c     |
        Not term   |   b    |     d     |

        where:
        a = f_d
        b = N_d - f_d
        c = f_r
        d = N_r - f_r

        G2 = 2 * Σ O_ij * ln(O_ij / E_ij)

        Args:
            f_d: Cluster frequency in domain
            N_d: Total cluster tokens in domain
            f_r: Cluster frequency in reference
            N_r: Total cluster tokens in reference

        Returns:
            Keyness LLR value (higher = more domain-specific)
        """
        import math

        a = f_d
        b = N_d - f_d
        c = f_r
        d = N_r - f_r

        # Total
        n = a + b + c + d

        if n == 0:
            return 0.0

        # Expected values
        e_a = (a + b) * (a + c) / n
        e_b = (a + b) * (b + d) / n
        e_c = (c + d) * (a + c) / n
        e_d = (c + d) * (b + d) / n

        # Compute LLR with safe handling of log(0)
        def safe_log_term(obs, exp):
            if obs == 0:
                return 0.0
            if exp == 0:
                return 0.0
            return obs * math.log(obs / exp)

        llr = 2 * (
            safe_log_term(a, e_a)
            + safe_log_term(b, e_b)
            + safe_log_term(c, e_c)
            + safe_log_term(d, e_d)
        )

        return llr

    def _compute_termhood_score(self, weirdness: float, keyness_llr: float, freq: int) -> float:
        """
        Compute composite termhood score for ranking.

        Score = log1p(keyness) * log1p(weirdness) * log1p(freq)

        Combines:
        - Statistical significance (keyness)
        - Domain specificity (weirdness)
        - Frequency evidence (freq)

        Args:
            weirdness: Weirdness ratio
            keyness_llr: Keyness LLR
            freq: Cluster frequency

        Returns:
            Composite termhood score
        """
        import math

        score = math.log1p(max(0, keyness_llr)) * math.log1p(max(0, weirdness)) * math.log1p(freq)

        return score

    def _list_clusters_with_termhood(
        self,
        session: Session,
        project_id: int,
        reference_project_id: int,
        *,
        top_n: int = 500,
        search: str | None = None,
        min_freq: int | None = None,
        source_filter: str | None = None,
    ) -> list[ClusterStats]:
        """
        List clusters with termhood metrics vs reference corpus.

        Args:
            session: DB session
            project_id: Domain project ID
            reference_project_id: Reference (general) project ID
            top_n: Limit results
            search: Search term
            min_freq: Minimum frequency filter
            source_filter: Source kind filter

        Returns:
            List of ClusterStats with termhood fields populated
        """
        from sqlalchemy import alias

        # Get total cluster tokens for both projects
        N_d = self._get_total_cluster_tokens(session, project_id)
        N_r = self._get_total_cluster_tokens(session, reference_project_id)

        if N_d == 0:
            logger.warning(f"No clusters found in domain project {project_id}")
            return []

        if N_r == 0:
            logger.warning(f"No clusters found in reference project {reference_project_id}")
            N_r = 1  # Avoid division by zero, treat as very small reference

        # Alias for reference clusters
        RefCluster = alias(TermCluster.__table__, name="ref_cluster")

        # Query domain clusters
        stmt = select(TermCluster).where(TermCluster.project_id == project_id)

        # Filter by source kind if specified
        if source_filter:
            stmt = (
                stmt.join(TermClusterMember)
                .join(Ngram)
                .where(Ngram.source_kind == source_filter)
                .distinct()
            )

        # Apply filters
        if min_freq:
            stmt = stmt.where(TermCluster.freq_abs >= min_freq)

        if search:
            search_variants = normalize_search_query(search)
            if search_variants:
                search_conditions = []
                for variant in search_variants:
                    search_conditions.append(TermCluster.representative_he.contains(variant))
                    search_conditions.append(TermCluster.canonical_key.contains(variant))
                    if TermCluster.representative_lemma is not None:
                        search_conditions.append(TermCluster.representative_lemma.contains(variant))
                stmt = stmt.where(or_(*search_conditions))
            else:
                stmt = stmt.where(TermCluster.representative_he.contains(search))

        # Execute query to get domain clusters
        domain_clusters = session.execute(stmt).scalars().all()

        # For each domain cluster, find matching reference cluster and compute termhood
        results = []

        for d_cluster in domain_clusters:
            f_d = d_cluster.freq_abs

            # Find matching reference cluster by canonical_key
            ref_stmt = select(TermCluster).where(
                and_(
                    TermCluster.project_id == reference_project_id,
                    TermCluster.canonical_key == d_cluster.canonical_key,
                )
            )
            r_cluster = session.execute(ref_stmt).scalar_one_or_none()

            # Get reference frequency (0 if not found)
            f_r = r_cluster.freq_abs if r_cluster else 0

            # Compute termhood metrics
            weirdness = self._compute_weirdness(f_d, N_d, f_r, N_r)
            keyness_llr = self._compute_keyness_llr(f_d, N_d, f_r, N_r)
            termhood_score = self._compute_termhood_score(weirdness, keyness_llr, f_d)

            results.append(
                ClusterStats(
                    cluster_id=d_cluster.cluster_id,
                    canonical_key=d_cluster.canonical_key,
                    representative_he=d_cluster.representative_he,
                    representative_lemma=d_cluster.representative_lemma,
                    freq_abs=d_cluster.freq_abs,
                    doc_freq=d_cluster.doc_freq,
                    members_count=d_cluster.members_count,
                    best_pmi=d_cluster.best_pmi,
                    best_llr=d_cluster.best_llr,
                    best_dice=d_cluster.best_dice,
                    best_tscore=d_cluster.best_tscore,
                    weirdness=weirdness,
                    keyness_llr=keyness_llr,
                    termhood_score=termhood_score,
                    entity_class=d_cluster.entity_class,
                    is_noise=d_cluster.is_noise,
                    noise_reason=d_cluster.noise_reason,
                    norm_text=d_cluster.norm_text,
                )
            )

        # Sort by termhood score (deterministic)
        results.sort(
            key=lambda c: (
                -c.termhood_score if c.termhood_score else 0,
                -c.keyness_llr if c.keyness_llr else 0,
                -c.weirdness if c.weirdness else 0,
                -c.doc_freq,
                -c.freq_abs,
                c.canonical_key,  # Stable tiebreaker
            )
        )

        # Limit results
        return results[:top_n]
