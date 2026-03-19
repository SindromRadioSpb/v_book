"""Sentence niqqud bootstrap pipeline — WAL-safe, chunked, cancel/pause-aware.

Modes:
  dry_run     — no DB writes; returns counters showing what would happen.
  fill_only   — insert/update only where src_hash changed or niqqud missing.
  rebuild     — re-generate all non-override rows.

Scopes are pre-resolved to sentence_ids by the caller (UI or worker).
See docs/SENTENCES_NIQQUD.md for full contract.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.infra.db_retry import with_retry_on_locked
from app.services.sentence_pronunciation_service import (
    GuardParams,
    SentencePronunciationService,
    SentenceSegmenter,
)

logger = logging.getLogger(__name__)


@dataclass
class SentenceBootstrapResult:
    """Counters returned by the bootstrap pipeline."""

    total_candidates: int = 0
    processed: int = 0
    inserted: int = 0
    updated: int = 0
    skipped_same_hash: int = 0
    skipped_has_override: int = 0
    skipped_too_short: int = 0
    skipped_too_long: int = 0
    skipped_non_hebrew_ratio: int = 0
    skipped_invalid_after_qc: int = 0
    failed: int = 0
    rejected_qc: int = 0
    partial_qc: int = 0
    dry_run: bool = False
    cancelled: bool = False
    generator_mode: str = "unknown"
    elapsed_seconds: float = 0.0

    @property
    def skipped_guard(self) -> int:
        return self.skipped_too_short + self.skipped_too_long + self.skipped_non_hebrew_ratio

    @property
    def skipped_total(self) -> int:
        return (
            self.skipped_same_hash
            + self.skipped_has_override
            + self.skipped_guard
            + self.skipped_invalid_after_qc
        )

    def summary_lines(self) -> list[str]:
        lines = [
            f"Total candidates : {self.total_candidates}",
            f"Processed        : {self.processed}",
            f"Inserted         : {self.inserted}",
            f"Updated          : {self.updated}",
            f"Skipped (total)  : {self.skipped_total}",
        ]
        if self.skipped_same_hash:
            lines.append(f"  same_hash      : {self.skipped_same_hash}")
        if self.skipped_has_override:
            lines.append(f"  has_override   : {self.skipped_has_override}")
        if self.skipped_too_short:
            lines.append(f"  too_short      : {self.skipped_too_short}")
        if self.skipped_too_long:
            lines.append(f"  too_long       : {self.skipped_too_long}")
        if self.skipped_non_hebrew_ratio:
            lines.append(f"  non_hebrew     : {self.skipped_non_hebrew_ratio}")
        if self.skipped_invalid_after_qc:
            lines.append(f"  qc_rejected    : {self.skipped_invalid_after_qc}")
        if self.failed:
            lines.append(f"Failed           : {self.failed}")
        if self.rejected_qc:
            lines.append(f"QC rejected      : {self.rejected_qc}")
        if self.partial_qc:
            lines.append(f"QC partial       : {self.partial_qc}")
        if self.dry_run:
            lines.append("(DRY RUN — no DB changes)")
        if self.cancelled:
            lines.append("(CANCELLED)")
        lines.append(f"Phonikud mode    : {self.generator_mode}")
        lines.append(f"Elapsed          : {self.elapsed_seconds:.1f}s")
        return lines


class SentencePronunciationBootstrapService:
    """Batch pipeline for sentence niqqud generation.

    Usage::

        svc = SentencePronunciationBootstrapService()
        result = svc.run(
            session, sentence_ids, lang="he",
            mode="fill_only",
            phonikud_generator=generator,
        )
    """

    def __init__(
        self,
        *,
        chunk_size: int = 200,
        sub_chunk_size: int = 50,
        max_segment_chars: int = 380,
    ):
        self._chunk_size = chunk_size
        self._sub_chunk_size = sub_chunk_size
        self._segmenter = SentenceSegmenter(max_chars=max_segment_chars)
        self._svc = SentencePronunciationService()

    def run(
        self,
        session: Session,
        sentence_ids: list[int],
        *,
        lang: str,
        mode: str = "fill_only",  # "dry_run" | "fill_only" | "rebuild"
        phonikud_generator,  # PronunciationGenerator-like with .generate() and .mode
        guard_params: GuardParams | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
        row_callback: Callable | None = None,  # (sid: int, niqqud: str|None, action: str)
        cancel_check: Callable[[], bool] | None = None,
        pause_check: Callable[[], bool] | None = None,
        phonikud_version: str | None = None,
    ) -> SentenceBootstrapResult:
        """Run the full bootstrap pipeline.

        Args:
            session: SQLAlchemy session (caller manages transaction lifecycle).
            sentence_ids: Pre-resolved list of sentence_ids to process.
            lang: Language code (e.g. "he").
            mode: "dry_run" | "fill_only" | "rebuild".
            phonikud_generator: Generator with .generate(lang, texts) → dict.
            guard_params: Optional override for min/max length and Hebrew ratio thresholds.
            progress_callback: Called as (processed_so_far, total, stage_label).
            row_callback: Optional per-row notification: (sentence_id, niqqud_or_None, action_str).
            cancel_check: Returns True to abort at next safe chunk boundary.
            pause_check: Returns True when paused; blocks until False.
            phonikud_version: Overrides auto-detected version from generator.mode.

        Returns:
            SentenceBootstrapResult with detailed counters.
        """
        result = SentenceBootstrapResult(
            total_candidates=len(sentence_ids),
            dry_run=(mode == "dry_run"),
        )
        t_start = time.monotonic()

        if not sentence_ids:
            result.elapsed_seconds = time.monotonic() - t_start
            return result

        # Detect generator mode
        _pv = str(phonikud_version or getattr(phonikud_generator, "mode", "unknown") or "unknown")
        result.generator_mode = _pv

        # Batch-fetch sentence texts for all IDs
        from app.services.sentences_workspace_service import SentencesWorkspaceService

        svc_ws = SentencesWorkspaceService()

        if progress_callback:
            progress_callback(0, len(sentence_ids), "Collecting sentences…")

        # Process in chunks to keep transactions short
        for chunk_start in range(0, len(sentence_ids), self._chunk_size):
            # ── Cancel / Pause check (safe boundary) ──────────────────────────
            if cancel_check and cancel_check():
                result.cancelled = True
                break
            while pause_check and pause_check():
                time.sleep(0.1)
                if cancel_check and cancel_check():
                    result.cancelled = True
                    break
            if result.cancelled:
                break

            chunk_ids = sentence_ids[chunk_start : chunk_start + self._chunk_size]
            text_map: dict[int, str] = svc_ws.get_sentence_texts_by_ids(session, chunk_ids)

            # ── Sub-chunk: apply guards + collect texts to generate ────────────
            to_generate: list[tuple[int, str, str]] = []  # (sentence_id, preprocessed, hash)

            for sid in chunk_ids:
                raw_text = text_map.get(sid)
                if not raw_text:
                    result.failed += 1
                    continue

                preprocessed = self._svc.preprocess_text(raw_text)
                ok, skip_reason = self._svc.should_process(preprocessed, guard=guard_params)
                if not ok:
                    result.processed += 1
                    self._increment_skip_reason(result, skip_reason)
                    if row_callback:
                        row_callback(sid, None, skip_reason)
                    continue

                src_hash = self._svc.compute_src_hash(lang, preprocessed, _pv)

                # Pre-check: existing row guard (skip_has_override, skip_same_hash)
                if mode != "dry_run":
                    from app.infra.sa_models import SentencePronunciation

                    existing = session.get(SentencePronunciation, sid)
                    if existing is not None:
                        if existing.is_override:
                            result.processed += 1
                            result.skipped_has_override += 1
                            if row_callback:
                                row_callback(sid, None, "skipped_has_override")
                            continue
                        if (
                            mode == "fill_only"
                            and existing.src_hash == src_hash
                            and existing.niqqud_text
                        ):
                            result.processed += 1
                            result.skipped_same_hash += 1
                            if row_callback:
                                row_callback(sid, None, "skipped_same_hash")
                            continue
                        if (
                            mode == "rebuild"
                            and existing.src_hash == src_hash
                            and existing.niqqud_text
                        ):
                            result.processed += 1
                            result.skipped_same_hash += 1
                            if row_callback:
                                row_callback(sid, None, "skipped_same_hash")
                            continue
                else:
                    # dry_run: still count what would happen
                    pass

                to_generate.append((sid, preprocessed, src_hash))

            if not to_generate:
                if progress_callback:
                    done = min(chunk_start + self._chunk_size, len(sentence_ids))
                    progress_callback(done, len(sentence_ids), "Generating…")
                continue

            # ── Generate in sub-chunks ─────────────────────────────────────────
            for sub_start in range(0, len(to_generate), self._sub_chunk_size):
                if cancel_check and cancel_check():
                    result.cancelled = True
                    break
                while pause_check and pause_check():
                    time.sleep(0.1)
                    if cancel_check and cancel_check():
                        result.cancelled = True
                        break
                if result.cancelled:
                    break

                sub_chunk = to_generate[sub_start : sub_start + self._sub_chunk_size]
                # Flatten texts (segmented if needed)
                generation_inputs: dict[int, list[str]] = {}
                for sid, preprocessed, src_hash in sub_chunk:
                    segments = self._segmenter.split(preprocessed)
                    generation_inputs[sid] = segments

                # Unique texts → batch generate
                all_texts = list({seg for segs in generation_inputs.values() for seg in segs})
                generated_map: dict[str, dict] = {}
                try:
                    generated_map = phonikud_generator.generate(lang, all_texts)
                    _pv = str(
                        phonikud_version
                        or getattr(phonikud_generator, "mode", None)
                        or _pv
                        or "unknown"
                    )
                    result.generator_mode = _pv
                except Exception as exc:
                    logger.error("Phonikud generation batch failed: %s", exc, exc_info=True)
                    # Record errors for all in this sub-chunk
                    if mode != "dry_run":
                        for sid, preprocessed, src_hash in sub_chunk:
                            try:
                                self._svc.record_error(
                                    session,
                                    sentence_id=sid,
                                    lang=lang,
                                    src_hash=src_hash,
                                    src_preprocessed=preprocessed,
                                    error_kind="generation_batch_error",
                                    error_details=str(exc)[:500],
                                    phonikud_version=_pv,
                                )
                            except Exception:
                                pass
                        with_retry_on_locked(
                            session.commit,
                            max_retries=4,
                            rollback_callback=session.rollback,
                        )
                    result.failed += len(sub_chunk)
                    result.processed += len(sub_chunk)
                    if row_callback:
                        for _sid, _, _ in sub_chunk:
                            row_callback(_sid, None, "failed")
                    continue

                # ── Write each row ─────────────────────────────────────────────
                for sid, preprocessed, src_hash in sub_chunk:
                    effective_src_hash = self._svc.compute_src_hash(lang, preprocessed, _pv)
                    segments = generation_inputs[sid]
                    # Assemble niqqud from segments
                    niqqud_parts = []
                    for seg in segments:
                        gen_result = generated_map.get(seg)
                        if gen_result and gen_result.get("niqqud_text"):
                            niqqud_parts.append(gen_result["niqqud_text"])
                        else:
                            niqqud_parts.append(seg)  # fallback: keep source segment

                    raw_niqqud = " ".join(niqqud_parts) if niqqud_parts else ""

                    # Sanitize output
                    from app.services.pronunciation_quality_service import (
                        PronunciationQualityService,
                    )

                    sanitized_niqqud = PronunciationQualityService.sanitize_tts_text(raw_niqqud)

                    # QC
                    qc_status, qc_reason, niqqud_coverage = self._svc.run_qc(sanitized_niqqud)

                    # Confidence from generator (use first segment's confidence, or fallback)
                    gen_result_first = generated_map.get(segments[0]) if segments else None
                    confidence = None
                    if gen_result_first:
                        confidence = gen_result_first.get("confidence")

                    result.processed += 1

                    if mode == "dry_run":
                        # Count what would happen; no DB write
                        if qc_status == "rejected":
                            result.skipped_invalid_after_qc += 1
                            if row_callback:
                                row_callback(sid, None, "dry_qc_rejected")
                        else:
                            result.inserted += 1  # approximate
                            if row_callback:
                                row_callback(sid, sanitized_niqqud, "dry_would_insert")
                        continue

                    # Store niqqud_text only for ok/partial/auto_fixed; None for rejected
                    store_niqqud = (
                        sanitized_niqqud if qc_status not in ("rejected", "failed") else None
                    )

                    try:
                        action = self._svc.upsert_auto(
                            session,
                            sentence_id=sid,
                            lang=lang,
                            src_hash=effective_src_hash,
                            src_preprocessed=preprocessed,
                            niqqud_text=store_niqqud,
                            confidence=confidence,
                            qc_status=qc_status,
                            qc_reason=qc_reason,
                            niqqud_coverage=niqqud_coverage,
                            phonikud_version=_pv,
                            mode="rebuild" if mode == "rebuild" else "fill_only",
                        )
                    except Exception as exc:
                        logger.error("Failed to upsert sentence %d: %s", sid, exc)
                        result.failed += 1
                        if row_callback:
                            row_callback(sid, None, "failed")
                        continue

                    if action == "inserted":
                        result.inserted += 1
                    elif action == "updated":
                        result.updated += 1
                    elif action == "skipped_same_hash":
                        result.skipped_same_hash += 1
                    elif action == "skipped_has_override":
                        result.skipped_has_override += 1

                    if qc_status == "rejected":
                        result.rejected_qc += 1
                    elif qc_status == "partial":
                        result.partial_qc += 1

                    if row_callback:
                        _rc_niqqud = store_niqqud if action in ("inserted", "updated") else None
                        row_callback(sid, _rc_niqqud, action)

            # ── Commit chunk ───────────────────────────────────────────────────
            if mode != "dry_run" and not result.cancelled:
                try:
                    with_retry_on_locked(
                        session.commit,
                        max_retries=4,
                        rollback_callback=session.rollback,
                    )
                except Exception as exc:
                    logger.error("Chunk commit failed: %s", exc)
                    session.rollback()

            if progress_callback:
                done = min(chunk_start + self._chunk_size, len(sentence_ids))
                progress_callback(done, len(sentence_ids), "Writing…")

        result.elapsed_seconds = time.monotonic() - t_start
        return result

    @staticmethod
    def _increment_skip_reason(result: SentenceBootstrapResult, skip_reason: str) -> None:
        if skip_reason == "skipped_too_short":
            result.skipped_too_short += 1
        elif skip_reason == "skipped_too_long":
            result.skipped_too_long += 1
        elif skip_reason == "skipped_non_hebrew_ratio":
            result.skipped_non_hebrew_ratio += 1
        else:
            result.skipped_too_short += 1  # fallback bucket
