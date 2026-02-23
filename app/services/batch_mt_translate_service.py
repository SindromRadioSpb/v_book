"""Batch MT Translation Service - PATCH-UI-BATCH-T01.

Service for batch translation of table rows (Dictionary, Terms, Translation Management).
Supports provider selection, write modes, chunked commits, and per-row error handling.
"""

import logging
import uuid
import time
from dataclasses import dataclass
from typing import List, Optional, Callable
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.infra.sa_models import TMEntry, TermCluster, Lemma
from app.services.translation_service import TranslationService
from app.services.tm_global_service import TMGlobalService
from app.domain.normalization.normalizer import normalize_for_tm

logger = logging.getLogger(__name__)


@dataclass
class BatchTranslateItem:
    """Single item to translate."""
    entity_type: str  # "lemma" | "term_cluster" | "tm_entry"
    entity_id: str  # Row identifier (lemma_text | representative_he | tm_id)
    source_text: str
    src_lang: str
    tgt_lang: str
    current_translation: Optional[str]
    project_id: Optional[int]


@dataclass
class BatchTranslateOptions:
    """Options for batch translation."""
    provider_mode: str  # "chain" | "force:<provider_id>"
    write_mode: str  # "FILL_EMPTY" | "OVERWRITE" | "SKIP_NON_EMPTY"
    chunk_size: int = 50
    stop_on_error: bool = False
    dry_run: bool = False


@dataclass
class BatchTranslateRowResult:
    """Result for a single row."""
    entity_id: str
    source_text: str
    old_translation: Optional[str]
    new_translation: Optional[str]
    provider_id: Optional[str]
    cache_hit: bool
    latency_ms: Optional[int]
    error_message: Optional[str]
    skipped: bool


@dataclass
class BatchTranslateResult:
    """Overall batch result."""
    total: int
    succeeded: int
    skipped: int
    failed: int
    row_results: List[BatchTranslateRowResult]
    trace_id: str
    elapsed_ms: int


class BatchMTTranslateService:
    """Service for batch MT translation of table rows."""

    def __init__(self):
        self.translation_service = TranslationService()

    def execute_batch(
        self,
        session: Session,
        items: List[BatchTranslateItem],
        options: BatchTranslateOptions,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        item_callback: Optional[Callable[["BatchTranslateRowResult"], None]] = None,  # PATCH-17-01: Per-item events
    ) -> BatchTranslateResult:
        """Execute batch translation.

        Args:
            session: DB session (caller manages transaction)
            items: List of items to translate
            options: Execution options
            progress_callback: Optional callback(completed, total)
            cancel_check: Optional callback() -> bool (True = cancel requested)
            item_callback: Optional callback(row_result) for real-time activity updates (PATCH-17-01)

        Returns:
            BatchTranslateResult with summary and per-row results
        """
        trace_id = str(uuid.uuid4())
        start_time = time.perf_counter()

        logger.info(
            f"[JOB:{trace_id[:8]}] Batch translate start: total={len(items)}, "
            f"provider_mode={options.provider_mode}, write_mode={options.write_mode}, "
            f"chunk_size={options.chunk_size}, dry_run={options.dry_run}"
        )

        row_results = []
        succeeded = 0
        skipped = 0
        failed = 0
        completed = 0

        # Process in chunks
        for chunk_start in range(0, len(items), options.chunk_size):
            chunk_end = min(chunk_start + options.chunk_size, len(items))
            chunk = items[chunk_start:chunk_end]

            # Check cancel before chunk
            if cancel_check and cancel_check():
                logger.info(f"Batch translate cancelled at row {completed}/{len(items)}")
                break

            try:
                # Process chunk
                chunk_results = self._process_chunk(
                    session, chunk, options, trace_id, cancel_check
                )

                row_results.extend(chunk_results)

                # Update counters
                for result in chunk_results:
                    if result.skipped:
                        skipped += 1
                    elif result.error_message:
                        failed += 1
                    else:
                        succeeded += 1

                    # PATCH-17-01: Call item_callback for real-time activity updates
                    if item_callback:
                        item_callback(result)

                completed += len(chunk_results)

                # Commit chunk (unless dry_run)
                if not options.dry_run:
                    session.commit()
                    chunk_succeeded = sum(1 for r in chunk_results if not r.skipped and not r.error_message)
                    chunk_failed = sum(1 for r in chunk_results if r.error_message)
                    logger.debug(
                        f"[JOB:{trace_id[:8]}] Committed chunk {chunk_start}-{chunk_end}: "
                        f"succeeded={chunk_succeeded}, failed={chunk_failed}"
                    )

                # Progress callback
                if progress_callback:
                    progress_callback(completed, len(items))

            except Exception as e:
                logger.error(f"Chunk {chunk_start}-{chunk_end} failed: {e}", exc_info=True)
                session.rollback()

                # Mark all chunk items as failed
                for item in chunk:
                    row_results.append(BatchTranslateRowResult(
                        entity_id=item.entity_id,
                        source_text=item.source_text,
                        old_translation=item.current_translation,
                        new_translation=None,
                        provider_id=None,
                        cache_hit=False,
                        latency_ms=None,
                        error_message=f"Chunk error: {str(e)}",
                        skipped=False,
                    ))
                    failed += 1
                    completed += 1

                if options.stop_on_error:
                    logger.info("stop_on_error=True, aborting batch")
                    break

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)

        result = BatchTranslateResult(
            total=len(items),
            succeeded=succeeded,
            skipped=skipped,
            failed=failed,
            row_results=row_results,
            trace_id=trace_id,
            elapsed_ms=elapsed_ms,
        )

        logger.info(
            f"[JOB:{trace_id[:8]}] Batch translate complete: "
            f"succeeded={succeeded}, skipped={skipped}, failed={failed}, "
            f"elapsed_ms={elapsed_ms}"
        )

        return result

    def _process_chunk(
        self,
        session: Session,
        chunk: List[BatchTranslateItem],
        options: BatchTranslateOptions,
        trace_id: str,
        cancel_check: Optional[Callable[[], bool]],
    ) -> List[BatchTranslateRowResult]:
        """Process a single chunk of items."""
        results = []

        for item in chunk:
            # Check cancel
            if cancel_check and cancel_check():
                # Mark remaining items as skipped
                results.append(BatchTranslateRowResult(
                    entity_id=item.entity_id,
                    source_text=item.source_text,
                    old_translation=item.current_translation,
                    new_translation=None,
                    provider_id=None,
                    cache_hit=False,
                    latency_ms=None,
                    error_message="Cancelled",
                    skipped=True,
                ))
                continue

            # Check write_mode (skip logic)
            if self._should_skip(item, options.write_mode):
                results.append(BatchTranslateRowResult(
                    entity_id=item.entity_id,
                    source_text=item.source_text,
                    old_translation=item.current_translation,
                    new_translation=None,
                    provider_id=None,
                    cache_hit=False,
                    latency_ms=None,
                    error_message=None,
                    skipped=True,
                ))
                continue

            # Translate and write
            result = self._translate_and_write(session, item, options, trace_id)
            results.append(result)

        return results

    def _should_skip(self, item: BatchTranslateItem, write_mode: str) -> bool:
        """Check if item should be skipped based on write_mode."""
        if write_mode == "FILL_EMPTY":
            # Skip if translation exists
            return bool(item.current_translation and item.current_translation.strip())
        elif write_mode == "SKIP_NON_EMPTY":
            # Skip if translation exists (same as FILL_EMPTY)
            return bool(item.current_translation and item.current_translation.strip())
        elif write_mode == "OVERWRITE":
            # Never skip
            return False
        else:
            logger.warning(f"Unknown write_mode: {write_mode}, defaulting to FILL_EMPTY")
            return bool(item.current_translation and item.current_translation.strip())

    def _translate_and_write(
        self,
        session: Session,
        item: BatchTranslateItem,
        options: BatchTranslateOptions,
        trace_id: str,
    ) -> BatchTranslateRowResult:
        """Translate a single item and write to DB."""
        row_start = time.perf_counter()

        try:
            # Validate input
            if not item.source_text or not item.source_text.strip():
                return BatchTranslateRowResult(
                    entity_id=item.entity_id,
                    source_text=item.source_text,
                    old_translation=item.current_translation,
                    new_translation=None,
                    provider_id=None,
                    cache_hit=False,
                    latency_ms=None,
                    error_message="Empty source text",
                    skipped=False,
                )

            # Translate: use force provider if specified, otherwise use chain
            if options.provider_mode.startswith("force:"):
                # Force provider mode: call provider directly
                force_provider_id = options.provider_mode.split(":", 1)[1]
                logger.info(f"Using force provider: {force_provider_id}")

                from app.infra.translators.providers_registry import ProvidersRegistry
                from app.infra.translators.base_provider import TranslationRequest

                registry = ProvidersRegistry()
                provider = registry.get(force_provider_id)

                if not provider:
                    logger.error(f"Force provider '{force_provider_id}' not found in registry")
                    return BatchTranslateRowResult(
                        entity_id=item.entity_id,
                        source_text=item.source_text,
                        old_translation=item.current_translation,
                        new_translation=None,
                        provider_id=None,
                        cache_hit=False,
                        latency_ms=int((time.perf_counter() - row_start) * 1000),
                        error_message=f"Provider '{force_provider_id}' not available",
                        skipped=False,
                    )

                # Call provider directly
                mt_request = TranslationRequest(
                    source_text=item.source_text,
                    source_lang=item.src_lang,
                    target_lang=item.tgt_lang,
                    glossary=None,  # TODO: Add glossary support
                )

                mt_result = provider.translate(mt_request)

                if mt_result.error_kind:
                    logger.error(f"Force provider '{force_provider_id}' failed: {mt_result.error_message}")
                    return BatchTranslateRowResult(
                        entity_id=item.entity_id,
                        source_text=item.source_text,
                        old_translation=item.current_translation,
                        new_translation=None,
                        provider_id=force_provider_id,
                        cache_hit=False,
                        latency_ms=mt_result.latency_ms,
                        error_message=mt_result.error_message,
                        skipped=False,
                    )

                # Success - create translation result
                from app.services.translation_service import TranslationResult as ServiceTranslationResult

                translation_result = ServiceTranslationResult(
                    translation=mt_result.translated_text,
                    source=force_provider_id,
                    confidence=1.0,
                )

            else:
                # Chain mode: use TranslationService
                translation_result = self.translation_service.resolve_translation(
                    session=session,
                    src_text=item.source_text,
                    kind=item.entity_type,
                    src_lang=item.src_lang,
                    tgt_lang=item.tgt_lang,
                    project_id=item.project_id,
                    use_mt=True,
                    allow_draft=False,
                )

            if not translation_result or not translation_result.translation:
                return BatchTranslateRowResult(
                    entity_id=item.entity_id,
                    source_text=item.source_text,
                    old_translation=item.current_translation,
                    new_translation=None,
                    provider_id=None,
                    cache_hit=False,
                    latency_ms=int((time.perf_counter() - row_start) * 1000),
                    error_message="No translation returned",
                    skipped=False,
                )

            # Write to DB (tab-specific logic)
            self._write_to_db(
                session,
                item,
                translation_result.translation,
                write_mode=options.write_mode,
            )

            latency_ms = int((time.perf_counter() - row_start) * 1000)

            # Extract metadata from translation_result
            provider_id = translation_result.source if translation_result.source != "tm" else None
            cache_hit = translation_result.source == "tm"

            logger.debug(
                f"Batch row translated: trace_id={trace_id}, entity_id={item.entity_id}, "
                f"provider_id={provider_id}, cache_hit={cache_hit}, latency_ms={latency_ms}"
            )

            return BatchTranslateRowResult(
                entity_id=item.entity_id,
                source_text=item.source_text,
                old_translation=item.current_translation,
                new_translation=translation_result.translation,
                provider_id=provider_id,
                cache_hit=cache_hit,
                latency_ms=latency_ms,
                error_message=None,
                skipped=False,
            )

        except Exception as e:
            logger.warning(
                f"[JOB:{trace_id[:8]}] Row translation failed: "
                f"entity_id={item.entity_id}, entity_type={item.entity_type}, "
                f"source_text='{item.source_text[:50] if item.source_text else '(empty)'}...', "
                f"error={str(e)}"
            )
            return BatchTranslateRowResult(
                entity_id=item.entity_id,
                source_text=item.source_text,
                old_translation=item.current_translation,
                new_translation=None,
                provider_id=None,
                cache_hit=False,
                latency_ms=int((time.perf_counter() - row_start) * 1000),
                error_message=str(e),
                skipped=False,
            )

    def _write_to_db(
        self,
        session: Session,
        item: BatchTranslateItem,
        translation: str,
        write_mode: str,
    ) -> None:
        """Write translation to DB using tab-specific logic.

        Args:
            session: DB session
            item: Item being translated
            translation: New translation text

        Raises:
            Exception: If write fails
        """
        force_global_update = write_mode == "OVERWRITE"

        if item.entity_type == "lemma":
            self._write_lemma(session, item, translation, force_global_update=force_global_update)
        elif item.entity_type == "term_cluster":
            self._write_term_cluster(session, item, translation, force_global_update=force_global_update)
        elif item.entity_type == "tm_entry":
            self._write_tm_entry(session, item, translation, force_global_update=force_global_update)
        elif item.entity_type == "surface":
            self._write_surface(session, item, translation, force_global_update=force_global_update)
        else:
            raise ValueError(f"Unknown entity_type: {item.entity_type}")

    def _write_lemma(
        self,
        session: Session,
        item: BatchTranslateItem,
        translation: str,
        force_global_update: bool = False,
    ) -> None:
        """Write lemma translation (Dictionary tab pattern)."""
        # PATCH-18-01: Compute src_norm (same as dictionary_view.py inline edit)
        normalized = normalize_for_tm(item.src_lang, item.source_text, "lemma")
        src_norm = normalized.norm

        # Check if TM entry exists
        stmt = select(TMEntry).where(
            TMEntry.project_id == item.project_id,
            TMEntry.kind == "lemma",
            TMEntry.src_norm == src_norm,
        )
        existing = session.execute(stmt).scalar()

        if existing:
            # Update existing
            existing.translation = translation
            existing.status = "approved"
            existing.origin = "mt_auto"  # Use existing origin value
            existing.updated_at = datetime.now()
            # PATCH-19-02: Upsert tm_global and link
            session.flush()
            TMGlobalService().upsert_and_link(
                session,
                existing,
                force_global_update=force_global_update,
            )
        else:
            # Look up source lemma for is_noise synchronization
            lemma_stmt = select(Lemma).where(
                Lemma.project_id == item.project_id,
                Lemma.norm_text == src_norm,
            )
            lemma = session.execute(lemma_stmt).scalar()

            # Create new TM entry with source_id link
            tm_entry = TMEntry(
                project_id=item.project_id,
                kind="lemma",
                src_lang=item.src_lang,
                tgt_lang=item.tgt_lang,
                src_text=item.source_text,
                src_norm=src_norm,  # Required NOT NULL field
                translation=translation,
                status="approved",
                origin="mt_auto",  # Use existing origin value
                lemma_id=lemma.lemma_id if lemma else None,
                is_noise=lemma.is_noise if lemma else 0,
                noise_reason=lemma.noise_reason if lemma else None,
            )
            session.add(tm_entry)
            # PATCH-19-02: Upsert tm_global and link
            session.flush()
            TMGlobalService().upsert_and_link(
                session,
                tm_entry,
                force_global_update=force_global_update,
            )

    def _write_term_cluster(
        self,
        session: Session,
        item: BatchTranslateItem,
        translation: str,
        force_global_update: bool = False,
    ) -> None:
        """Write term cluster translation (Terms tab pattern)."""
        # Compute src_norm (same as terms_view.py)
        normalized = normalize_for_tm(item.src_lang, item.source_text, "term_cluster")
        src_norm = normalized.norm

        # Check if TM entry exists
        stmt = select(TMEntry).where(
            TMEntry.project_id == item.project_id,
            TMEntry.kind == "term_cluster",
            TMEntry.src_norm == src_norm,
        )
        existing = session.execute(stmt).scalar()

        if existing:
            # Update existing
            existing.translation = translation
            existing.status = "approved"
            existing.origin = "mt_auto"  # Use existing origin value
            existing.updated_at = datetime.now()
            # PATCH-19-02: Upsert tm_global and link
            session.flush()
            TMGlobalService().upsert_and_link(
                session,
                existing,
                force_global_update=force_global_update,
            )
        else:
            # Look up source cluster for is_noise synchronization
            cluster_stmt = select(TermCluster).where(
                TermCluster.project_id == item.project_id,
                TermCluster.norm_text == src_norm,
            )
            cluster = session.execute(cluster_stmt).scalar()

            # Create new TM entry with source_id link
            tm_entry = TMEntry(
                project_id=item.project_id,
                kind="term_cluster",
                src_lang=item.src_lang,
                tgt_lang=item.tgt_lang,
                src_text=item.source_text,
                src_norm=src_norm,
                translation=translation,
                status="approved",
                origin="mt_auto",  # Use existing origin value
                source_ref="batch_translate",
                cluster_id=cluster.cluster_id if cluster else None,
                is_noise=cluster.is_noise if cluster else 0,
                noise_reason=cluster.noise_reason if cluster else None,
            )
            session.add(tm_entry)
            # PATCH-19-02: Upsert tm_global and link
            session.flush()
            TMGlobalService().upsert_and_link(
                session,
                tm_entry,
                force_global_update=force_global_update,
            )

    def _write_tm_entry(
        self,
        session: Session,
        item: BatchTranslateItem,
        translation: str,
        force_global_update: bool = False,
    ) -> None:
        """Write TM entry translation (Translation Management tab pattern).

        Uses TranslationAdminService pattern: update translation only, preserve status/origin.
        """
        # Get existing entry by ID
        tm_id = int(item.entity_id)
        stmt = select(TMEntry).where(TMEntry.tm_id == tm_id)
        entry = session.execute(stmt).scalar()

        if not entry:
            raise ValueError(f"TM entry not found: tm_id={tm_id}")

        # Update translation only (preserve status, origin)
        entry.translation = translation
        entry.updated_at = datetime.now()
        # PATCH-19-02: Upsert tm_global and link
        session.flush()
        TMGlobalService().upsert_and_link(
            session,
            entry,
            force_global_update=force_global_update,
        )

        # Note: We don't create history here (TranslationAdminService does that)
        # For batch operations, we prioritize performance over history granularity

    def _write_surface(
        self,
        session: Session,
        item: "BatchTranslateItem",
        translation: str,
        force_global_update: bool = False,
    ) -> None:
        """Write surface-level translation (Sentences workspace pattern).

        Upserts a kind='surface' TM entry keyed by src_norm.
        This is the same layer that SentencesWorkspaceService._batch_get_translations reads.
        """
        normalized = normalize_for_tm(item.src_lang, item.source_text, "surface")
        src_norm = normalized.norm
        sentence_source_ref = "batch_translate"
        try:
            sentence_source_ref = f"sentence:{int(item.entity_id)}"
        except (TypeError, ValueError):
            sentence_source_ref = "batch_translate"

        stmt = select(TMEntry).where(
            TMEntry.project_id == item.project_id,
            TMEntry.kind == "surface",
            TMEntry.src_norm == src_norm,
        )
        existing = session.execute(stmt).scalar()

        if existing:
            existing.translation = translation
            existing.status = "approved"
            existing.origin = "mt_auto"
            existing.source_ref = sentence_source_ref
            existing.updated_at = datetime.now()
            session.flush()
            TMGlobalService().upsert_and_link(
                session, existing, force_global_update=force_global_update
            )
        else:
            tm_entry = TMEntry(
                project_id=item.project_id,
                kind="surface",
                src_lang=item.src_lang,
                tgt_lang=item.tgt_lang,
                src_text=item.source_text,
                src_norm=src_norm,
                translation=translation,
                status="approved",
                origin="mt_auto",
                source_ref=sentence_source_ref,
            )
            session.add(tm_entry)
            session.flush()
            TMGlobalService().upsert_and_link(
                session, tm_entry, force_global_update=force_global_update
            )
