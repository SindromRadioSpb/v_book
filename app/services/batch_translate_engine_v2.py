"""Batch Translate Engine V2 - Production-grade batch translation engine.

PATCH-01: Complete redesign of batch translation for Dictionary/Terms/TM.

Key Features:
- Tab-agnostic: Works with any entity type (lemma, term_cluster, tm_entry)
- Deduplication: Translates unique source_text only once
- Chunked processing: Configurable chunk size with atomic commits
- Async-friendly: Designed for QThread/background execution
- Provider modes: chain (default) | force:<provider_id>
- Write modes: fill_empty | overwrite | skip_nonempty
- Error resilience: Per-row error handling, no cascade failures
- Observability: Job ID correlation, detailed telemetry

Architecture:
1. Accept List[BatchTranslateItem] (entity_type, entity_id, source_text, current_translation)
2. Dedupe by source_text → build translation map
3. Translate unique texts (via TranslationService or direct provider)
4. Apply write_mode logic per row
5. Write to DB in chunks (atomic commits)
6. Return Result with per-row details

Usage:
    engine = BatchTranslateEngineV2()
    result = engine.execute(items, options, session)
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Callable, Dict, Set
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.infra.sa_models import TMEntry
from app.services.translation_service import TranslationService
from app.infra.translators.providers_registry import ProvidersRegistry
from app.domain.normalization.normalizer import normalize_for_tm

logger = logging.getLogger(__name__)


# ============================================================================
# Data Transfer Objects
# ============================================================================


@dataclass
class BatchTranslateItem:
    """Single item to translate."""
    entity_type: str  # "lemma" | "term_cluster" | "tm_entry"
    entity_id: str  # Unique identifier within entity_type
    source_text: str
    src_lang: str
    tgt_lang: str
    current_translation: Optional[str]
    project_id: Optional[int]


@dataclass
class BatchTranslateOptions:
    """Batch translation execution options."""
    provider_mode: str = "chain"  # "chain" | "force:<provider_id>"
    write_mode: str = "fill_empty"  # "fill_empty" | "overwrite" | "skip_nonempty"
    chunk_size: int = 50
    dry_run: bool = False
    stop_on_error: bool = False


@dataclass
class RowResult:
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
class BatchResult:
    """Overall batch result."""
    total: int
    succeeded: int
    skipped: int
    failed: int
    job_id: str
    elapsed_ms: int
    row_results: List[RowResult] = field(default_factory=list)


# ============================================================================
# Batch Translate Engine V2
# ============================================================================


class BatchTranslateEngineV2:
    """Production-grade batch translation engine."""

    def __init__(self):
        self.translation_service = TranslationService()
        self.providers_registry = ProvidersRegistry()

    def execute(
        self,
        session: Session,
        items: List[BatchTranslateItem],
        options: BatchTranslateOptions,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> BatchResult:
        """Execute batch translation.

        Args:
            session: SQLAlchemy session (caller manages transaction)
            items: List of items to translate
            options: Execution options
            progress_callback: Optional callback(completed, total)
            cancel_check: Optional callback() -> bool (True = cancel requested)

        Returns:
            BatchResult with summary and per-row results
        """
        job_id = str(uuid.uuid4())
        start_time = time.perf_counter()

        logger.info(
            f"[JOB:{job_id[:8]}] BatchEngineV2 start: total={len(items)}, "
            f"provider_mode={options.provider_mode}, write_mode={options.write_mode}"
        )

        # Phase 1: Dedupe and prepare translation map
        unique_texts = self._dedupe_items(items)
        logger.info(f"[JOB:{job_id[:8]}] Deduped: {len(items)} items → {len(unique_texts)} unique texts")

        # Phase 2: Translate unique texts
        translation_map = self._translate_unique_texts(
            session,
            unique_texts,
            options,
            job_id,
            cancel_check,
        )

        if cancel_check and cancel_check():
            logger.info(f"[JOB:{job_id[:8]}] Cancelled after translation phase")
            return self._build_cancelled_result(items, job_id, start_time)

        # Phase 3: Process items with translations
        row_results = self._process_items(
            session,
            items,
            translation_map,
            options,
            job_id,
            progress_callback,
            cancel_check,
        )

        # Phase 4: Build result
        succeeded = sum(1 for r in row_results if not r.skipped and not r.error_message)
        skipped = sum(1 for r in row_results if r.skipped)
        failed = sum(1 for r in row_results if r.error_message)
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)

        result = BatchResult(
            total=len(items),
            succeeded=succeeded,
            skipped=skipped,
            failed=failed,
            job_id=job_id,
            elapsed_ms=elapsed_ms,
            row_results=row_results,
        )

        logger.info(
            f"[JOB:{job_id[:8]}] BatchEngineV2 complete: "
            f"succeeded={succeeded}, skipped={skipped}, failed={failed}, elapsed_ms={elapsed_ms}"
        )

        return result

    def _dedupe_items(self, items: List[BatchTranslateItem]) -> Set[tuple]:
        """Extract unique (src_text, src_lang, tgt_lang) tuples."""
        unique = set()
        for item in items:
            if item.source_text and item.source_text.strip():
                unique.add((item.source_text, item.src_lang, item.tgt_lang))
        return unique

    def _translate_unique_texts(
        self,
        session: Session,
        unique_texts: Set[tuple],
        options: BatchTranslateOptions,
        job_id: str,
        cancel_check: Optional[Callable[[], bool]],
    ) -> Dict[tuple, str]:
        """Translate unique texts and return mapping.

        Returns:
            Dict[(src_text, src_lang, tgt_lang)] -> translated_text
        """
        translation_map = {}
        total = len(unique_texts)
        completed = 0

        logger.info(f"[JOB:{job_id[:8]}] Translating {total} unique texts...")

        for src_text, src_lang, tgt_lang in unique_texts:
            if cancel_check and cancel_check():
                logger.info(f"[JOB:{job_id[:8]}] Translation phase cancelled at {completed}/{total}")
                break

            try:
                # Translate via TranslationService or forced provider
                if options.provider_mode.startswith("force:"):
                    provider_id = options.provider_mode.split(":", 1)[1]
                    translated = self._translate_with_provider(
                        provider_id, src_text, src_lang, tgt_lang
                    )
                else:
                    # Use TranslationService (provider chain)
                    translated = self._translate_with_service(
                        session, src_text, src_lang, tgt_lang
                    )

                if translated:
                    translation_map[(src_text, src_lang, tgt_lang)] = translated

                completed += 1

            except Exception as e:
                logger.warning(
                    f"[JOB:{job_id[:8]}] Failed to translate '{src_text[:50]}...': {e}"
                )
                # Continue with other texts (resilient)

        logger.info(
            f"[JOB:{job_id[:8]}] Translation phase complete: {len(translation_map)}/{total} succeeded"
        )

        return translation_map

    def _translate_with_service(
        self,
        session: Session,
        src_text: str,
        src_lang: str,
        tgt_lang: str,
    ) -> Optional[str]:
        """Translate using TranslationService (provider chain)."""
        result = self.translation_service.resolve_translation(
            session=session,
            src_text=src_text,
            kind="generic",  # Not tied to specific kind for dedupe
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            project_id=None,  # Use global TM only
            use_mt=True,
            allow_draft=False,
        )
        return result.translation if result else None

    def _translate_with_provider(
        self,
        provider_id: str,
        src_text: str,
        src_lang: str,
        tgt_lang: str,
    ) -> Optional[str]:
        """Translate using specific provider (force mode)."""
        provider = self.providers_registry.get(provider_id)
        if not provider:
            raise ValueError(f"Provider not found: {provider_id}")

        # Use provider directly
        from app.infra.translators.base_provider import TranslationRequest
        request = TranslationRequest(
            text=src_text,
            source_lang=src_lang,
            target_lang=tgt_lang,
        )
        result = provider.translate(request)
        return result.translated_text if result and not result.error else None

    def _process_items(
        self,
        session: Session,
        items: List[BatchTranslateItem],
        translation_map: Dict[tuple, str],
        options: BatchTranslateOptions,
        job_id: str,
        progress_callback: Optional[Callable[[int, int], None]],
        cancel_check: Optional[Callable[[], bool]],
    ) -> List[RowResult]:
        """Process items in chunks, apply write_mode, commit to DB."""
        row_results = []
        completed = 0
        total = len(items)

        # Process in chunks
        for chunk_start in range(0, total, options.chunk_size):
            if cancel_check and cancel_check():
                logger.info(f"[JOB:{job_id[:8]}] Processing cancelled at {completed}/{total}")
                # Mark remaining as skipped
                for i in range(chunk_start, total):
                    item = items[i]
                    row_results.append(RowResult(
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
                break

            chunk_end = min(chunk_start + options.chunk_size, total)
            chunk = items[chunk_start:chunk_end]

            try:
                # Process chunk
                chunk_results = self._process_chunk(
                    session, chunk, translation_map, options, job_id
                )
                row_results.extend(chunk_results)

                # Commit chunk (unless dry_run)
                if not options.dry_run:
                    session.commit()
                    chunk_succeeded = sum(1 for r in chunk_results if not r.skipped and not r.error_message)
                    logger.debug(
                        f"[JOB:{job_id[:8]}] Committed chunk {chunk_start}-{chunk_end}: succeeded={chunk_succeeded}"
                    )

                completed += len(chunk)

                # Progress callback
                if progress_callback:
                    progress_callback(completed, total)

            except Exception as e:
                logger.error(f"[JOB:{job_id[:8]}] Chunk {chunk_start}-{chunk_end} failed: {e}", exc_info=True)
                session.rollback()

                # Mark chunk items as failed
                for item in chunk:
                    row_results.append(RowResult(
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

                completed += len(chunk)

                if options.stop_on_error:
                    logger.info(f"[JOB:{job_id[:8]}] stop_on_error=True, aborting")
                    break

        return row_results

    def _process_chunk(
        self,
        session: Session,
        chunk: List[BatchTranslateItem],
        translation_map: Dict[tuple, str],
        options: BatchTranslateOptions,
        job_id: str,
    ) -> List[RowResult]:
        """Process a single chunk of items."""
        results = []

        for item in chunk:
            row_start = time.perf_counter()

            # Check skip logic (write_mode)
            if self._should_skip(item, options.write_mode):
                results.append(RowResult(
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

            # Get translation from map
            key = (item.source_text, item.src_lang, item.tgt_lang)
            translation = translation_map.get(key)

            if not translation:
                results.append(RowResult(
                    entity_id=item.entity_id,
                    source_text=item.source_text,
                    old_translation=item.current_translation,
                    new_translation=None,
                    provider_id=None,
                    cache_hit=False,
                    latency_ms=int((time.perf_counter() - row_start) * 1000),
                    error_message="No translation available",
                    skipped=False,
                ))
                continue

            # Write to DB
            try:
                self._write_to_db(session, item, translation)

                results.append(RowResult(
                    entity_id=item.entity_id,
                    source_text=item.source_text,
                    old_translation=item.current_translation,
                    new_translation=translation,
                    provider_id="dedupe",  # From translation map
                    cache_hit=False,
                    latency_ms=int((time.perf_counter() - row_start) * 1000),
                    error_message=None,
                    skipped=False,
                ))

            except Exception as e:
                logger.warning(
                    f"[JOB:{job_id[:8]}] Failed to write {item.entity_type}/{item.entity_id}: {e}"
                )
                results.append(RowResult(
                    entity_id=item.entity_id,
                    source_text=item.source_text,
                    old_translation=item.current_translation,
                    new_translation=None,
                    provider_id=None,
                    cache_hit=False,
                    latency_ms=int((time.perf_counter() - row_start) * 1000),
                    error_message=str(e),
                    skipped=False,
                ))

        return results

    def _should_skip(self, item: BatchTranslateItem, write_mode: str) -> bool:
        """Check if item should be skipped based on write_mode."""
        if write_mode == "fill_empty":
            return bool(item.current_translation and item.current_translation.strip())
        elif write_mode == "skip_nonempty":
            return bool(item.current_translation and item.current_translation.strip())
        elif write_mode == "overwrite":
            return False
        else:
            logger.warning(f"Unknown write_mode: {write_mode}, defaulting to fill_empty")
            return bool(item.current_translation and item.current_translation.strip())

    def _write_to_db(
        self,
        session: Session,
        item: BatchTranslateItem,
        translation: str,
    ) -> None:
        """Write translation to DB (tab-specific logic)."""
        if item.entity_type == "lemma":
            self._write_lemma(session, item, translation)
        elif item.entity_type == "term_cluster":
            self._write_term_cluster(session, item, translation)
        elif item.entity_type == "tm_entry":
            self._write_tm_entry(session, item, translation)
        else:
            raise ValueError(f"Unknown entity_type: {item.entity_type}")

    def _write_lemma(self, session: Session, item: BatchTranslateItem, translation: str):
        """Write lemma translation to TM."""
        src_norm = item.source_text  # Lemma: src_norm == src_text

        stmt = select(TMEntry).where(
            TMEntry.project_id == item.project_id,
            TMEntry.kind == "lemma",
            TMEntry.src_norm == src_norm,
        )
        existing = session.execute(stmt).scalar()

        if existing:
            existing.translation = translation
            existing.status = "approved"
            existing.origin = "mt_auto"
            existing.updated_at = datetime.now()
        else:
            tm_entry = TMEntry(
                project_id=item.project_id,
                kind="lemma",
                src_lang=item.src_lang,
                tgt_lang=item.tgt_lang,
                src_text=item.source_text,
                src_norm=src_norm,
                translation=translation,
                status="approved",
                origin="mt_auto",
            )
            session.add(tm_entry)

    def _write_term_cluster(self, session: Session, item: BatchTranslateItem, translation: str):
        """Write term cluster translation to TM."""
        # CRITICAL: Proper normalization for term_cluster
        try:
            normalized = normalize_for_tm(item.src_lang, item.source_text, "term_cluster")
            src_norm = normalized.norm

            if not src_norm or not src_norm.strip():
                raise ValueError(f"normalize_for_tm returned empty src_norm for: {item.source_text}")

        except Exception as e:
            raise ValueError(f"Normalization failed for term '{item.source_text}': {e}")

        stmt = select(TMEntry).where(
            TMEntry.project_id == item.project_id,
            TMEntry.kind == "term_cluster",
            TMEntry.src_norm == src_norm,
        )
        existing = session.execute(stmt).scalar()

        if existing:
            existing.translation = translation
            existing.status = "approved"
            existing.origin = "mt_auto"
            existing.updated_at = datetime.now()
        else:
            tm_entry = TMEntry(
                project_id=item.project_id,
                kind="term_cluster",
                src_lang=item.src_lang,
                tgt_lang=item.tgt_lang,
                src_text=item.source_text,
                src_norm=src_norm,
                translation=translation,
                status="approved",
                origin="mt_auto",
                source_ref="batch_translate_v2",
            )
            session.add(tm_entry)

    def _write_tm_entry(self, session: Session, item: BatchTranslateItem, translation: str):
        """Write TM entry translation (Translation Management tab)."""
        tm_id = int(item.entity_id)
        stmt = select(TMEntry).where(TMEntry.tm_id == tm_id)
        entry = session.execute(stmt).scalar()

        if not entry:
            raise ValueError(f"TM entry not found: tm_id={tm_id}")

        entry.translation = translation
        entry.updated_at = datetime.now()

    def _build_cancelled_result(
        self,
        items: List[BatchTranslateItem],
        job_id: str,
        start_time: float,
    ) -> BatchResult:
        """Build result for cancelled job."""
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        row_results = [
            RowResult(
                entity_id=item.entity_id,
                source_text=item.source_text,
                old_translation=item.current_translation,
                new_translation=None,
                provider_id=None,
                cache_hit=False,
                latency_ms=None,
                error_message="Cancelled",
                skipped=True,
            )
            for item in items
        ]

        return BatchResult(
            total=len(items),
            succeeded=0,
            skipped=len(items),
            failed=0,
            job_id=job_id,
            elapsed_ms=elapsed_ms,
            row_results=row_results,
        )
