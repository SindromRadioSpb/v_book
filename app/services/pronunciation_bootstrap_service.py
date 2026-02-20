"""Offline bootstrap for pronunciation layer."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import asc, select
from sqlalchemy.orm import Session

from app.infra.pronunciation import PhonikudAdapter, PhonikudHealthReport, PhonikudMode
from app.infra.sa_models import Lemma, TermCluster, UserDictionaryItem
from app.services.pronunciation_quality_service import PronunciationQualityService
from app.services.pronunciation_service import PronunciationService

logger = logging.getLogger(__name__)


@dataclass
class PronunciationBootstrapResult:
    total_candidates: int
    generated_candidates: int
    updated: int
    skipped: int
    failed: int
    cancelled: bool = False
    generator_mode: str = "fallback"


class PronunciationGenerator:
    """Generator interface for offline pronunciation enrichment."""

    def generate(self, lang: str, source_texts: List[str]) -> Dict[str, Dict[str, Optional[str]]]:
        raise NotImplementedError


class NoopPronunciationGenerator(PronunciationGenerator):
    """Fallback generator that produces no entries."""

    def generate(self, lang: str, source_texts: List[str]) -> Dict[str, Dict[str, Optional[str]]]:
        _ = lang
        _ = source_texts
        return {}


class PhonikudPronunciationGenerator(PronunciationGenerator):
    """Best-effort adapter for local Phonikud-like libraries."""

    def __init__(self, *, strict: bool = False, model_path: Optional[str] = None, enabled: bool = True):
        self.strict = strict
        self._adapter = PhonikudAdapter(model_path=model_path, enabled=enabled)

    @property
    def mode(self) -> str:
        return self._adapter.last_mode

    def health_check(self, sample_texts: Optional[List[str]] = None) -> PhonikudHealthReport:
        return self._adapter.health_check(sample_texts)

    def generate(self, lang: str, source_texts: List[str]) -> Dict[str, Dict[str, Optional[str]]]:
        if lang.strip().lower() not in {"he", "he-il"}:
            return {}
        if not self._adapter.is_available():
            if self.strict:
                raise RuntimeError("Phonikud generator is not available")
            return {}
        generated = self._adapter.infer(source_texts)
        mode = self._adapter.last_mode
        confidence = 0.8 if mode == PhonikudMode.REAL_INFERENCE.value else 0.2

        result: Dict[str, Dict[str, Optional[str]]] = {}
        for source_text in source_texts:
            try:
                niqqud = generated.get(source_text)
                if niqqud and str(niqqud).strip():
                    result[source_text] = {
                        "niqqud_text": str(niqqud).strip(),
                        "ipa": None,
                        "reading_text": None,
                        "source": "auto_phonikud",
                        "confidence": confidence,
                        "notes": f"auto:phonikud:{mode}",
                    }
            except Exception as exc:
                logger.debug("Phonikud generation failed for '%s': %s", source_text, exc)
        return result

class PronunciationBootstrapService:
    """Build pronunciation entries from existing lexical corpus."""

    def __init__(
        self,
        *,
        pronunciation_service: Optional[PronunciationService] = None,
        generator: Optional[PronunciationGenerator] = None,
    ):
        self.pronunciation_service = pronunciation_service or PronunciationService()
        self.generator = generator or NoopPronunciationGenerator()

    @staticmethod
    def _candidate_rank(text_value: str, source_priority: int, row_id: int) -> Tuple[int, int, int, int, str]:
        text_clean = (text_value or "").strip()
        has_separator = 1 if ("_" in text_clean or "|" in text_clean) else 0
        has_space = 0 if " " in text_clean else 1
        return (
            has_separator,          # Prefer separator-free source text.
            has_space,              # Prefer phrase-like values with spaces.
            -len(text_clean),       # Prefer longer surface forms (keeps prefixes/articles).
            source_priority,        # Stable source precedence.
            row_id,                 # Stable deterministic tie-breaker.
        )

    def collect_source_candidates(
        self,
        session: Session,
        *,
        lang: str,
        include_lemmas: bool = True,
        include_terms: bool = True,
        include_user_dictionary: bool = True,
    ) -> Dict[str, str]:
        """Collect deterministic `(src_norm -> preferred source_text)` map."""
        selected: Dict[str, Tuple[Tuple[int, int, int, int, str], str]] = {}

        def pick(norm_value: Optional[str], text_value: Optional[str], source_priority: int, row_id: int) -> None:
            norm = (norm_value or "").strip()
            text = (text_value or "").strip()
            if not norm or not text:
                return
            rank = self._candidate_rank(text, source_priority, row_id)
            current = selected.get(norm)
            if current is None or rank < current[0]:
                selected[norm] = (rank, text)

        if include_lemmas:
            try:
                lemma_rows = session.execute(
                    select(Lemma.lemma_id, Lemma.norm_text, Lemma.lemma_text)
                    .where(Lemma.norm_text.is_not(None))
                    .where(Lemma.lemma_text.is_not(None))
                    .order_by(asc(Lemma.norm_text), asc(Lemma.lemma_id))
                ).all()
                for lemma_id, norm_text, lemma_text in lemma_rows:
                    pick(norm_text, lemma_text, 0, int(lemma_id or 0))
            except Exception as exc:
                logger.debug("collect_source_candidates lemmas skipped: %s", exc)

        if include_terms:
            try:
                term_rows = session.execute(
                    select(TermCluster.cluster_id, TermCluster.norm_text, TermCluster.representative_he)
                    .where(TermCluster.norm_text.is_not(None))
                    .where(TermCluster.representative_he.is_not(None))
                    .order_by(asc(TermCluster.norm_text), asc(TermCluster.cluster_id))
                ).all()
                for cluster_id, norm_text, representative_he in term_rows:
                    pick(norm_text, representative_he, 1, int(cluster_id or 0))
            except Exception as exc:
                logger.debug("collect_source_candidates terms skipped: %s", exc)

        if include_user_dictionary:
            try:
                ud_rows = session.execute(
                    select(UserDictionaryItem.item_id, UserDictionaryItem.src_norm, UserDictionaryItem.src_text)
                    .where(UserDictionaryItem.src_lang == lang)
                    .where(UserDictionaryItem.src_norm.is_not(None))
                    .where(UserDictionaryItem.src_text.is_not(None))
                    .order_by(asc(UserDictionaryItem.src_norm), asc(UserDictionaryItem.item_id))
                ).all()
                for item_id, src_norm, src_text in ud_rows:
                    pick(src_norm, src_text, 2, int(item_id or 0))
            except Exception as exc:
                logger.debug("collect_source_candidates user_dictionary skipped: %s", exc)

        return {src_norm: text for src_norm, (_rank, text) in selected.items()}

    def collect_unique_src_norms(
        self,
        session: Session,
        *,
        lang: str,
        include_lemmas: bool = True,
        include_terms: bool = True,
        include_user_dictionary: bool = True,
    ) -> List[str]:
        """Collect unique source norms from lexical tables."""
        values = set()

        if include_lemmas:
            try:
                lemma_rows = session.execute(
                    select(Lemma.norm_text)
                    .where(Lemma.norm_text.is_not(None))
                    .order_by(asc(Lemma.norm_text))
                ).scalars().all()
                values.update(v.strip() for v in lemma_rows if (v or "").strip())
            except Exception as exc:
                logger.debug("collect_unique_src_norms lemmas skipped: %s", exc)

        if include_terms:
            try:
                term_rows = session.execute(
                    select(TermCluster.norm_text)
                    .where(TermCluster.norm_text.is_not(None))
                    .order_by(asc(TermCluster.norm_text))
                ).scalars().all()
                values.update(v.strip() for v in term_rows if (v or "").strip())
            except Exception as exc:
                logger.debug("collect_unique_src_norms terms skipped: %s", exc)

        if include_user_dictionary:
            try:
                ud_rows = session.execute(
                    select(UserDictionaryItem.src_norm)
                    .where(UserDictionaryItem.src_lang == lang)
                    .where(UserDictionaryItem.src_norm.is_not(None))
                    .order_by(asc(UserDictionaryItem.src_norm))
                ).scalars().all()
                values.update(v.strip() for v in ud_rows if (v or "").strip())
            except Exception as exc:
                logger.debug("collect_unique_src_norms user_dictionary skipped: %s", exc)

        return sorted(values)

    def bootstrap(
        self,
        session: Session,
        *,
        lang: str,
        chunk_size: int = 500,
        rebuild_auto: bool = False,
        limit: Optional[int] = None,
        include_lemmas: bool = True,
        include_terms: bool = True,
        include_user_dictionary: bool = True,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> PronunciationBootstrapResult:
        """Bootstrap pronunciation entries from available lexical norms."""
        source_candidates = self.collect_source_candidates(
            session,
            lang=lang,
            include_lemmas=include_lemmas,
            include_terms=include_terms,
            include_user_dictionary=include_user_dictionary,
        )
        if not source_candidates:
            # Backward-compat fallback for slim fixture DBs and legacy tests.
            fallback_norms = self.collect_unique_src_norms(
                session,
                lang=lang,
                include_lemmas=include_lemmas,
                include_terms=include_terms,
                include_user_dictionary=include_user_dictionary,
            )
            source_candidates = {norm: norm for norm in fallback_norms}

        ordered_norms = sorted(source_candidates.keys())
        if limit is not None and int(limit) > 0:
            ordered_norms = ordered_norms[: int(limit)]
        total = len(ordered_norms)
        if total == 0:
            return PronunciationBootstrapResult(
                total_candidates=0,
                generated_candidates=0,
                updated=0,
                skipped=0,
                failed=0,
            )

        generated_candidates = 0
        updated = 0
        skipped = 0
        failed = 0
        cancelled = False
        processed = 0
        chunk_size = max(1, int(chunk_size))

        for idx in range(0, total, chunk_size):
            if cancel_check and cancel_check():
                cancelled = True
                break
            chunk_norms = ordered_norms[idx : idx + chunk_size]
            chunk_sources = [source_candidates[src_norm] for src_norm in chunk_norms]
            generated_map = self.generator.generate(lang, chunk_sources)
            generated_candidates += len(generated_map or {})

            entries = []
            for src_norm in chunk_norms:
                source_text = source_candidates[src_norm]
                item = generated_map.get(source_text) or generated_map.get(src_norm)
                if not item:
                    continue
                niqqud_result = PronunciationQualityService.normalize_field(
                    item.get("niqqud_text"),
                    strict=False,
                )
                if not niqqud_result.is_valid:
                    failed += 1
                    continue
                notes_value = (item.get("notes") or "").strip()
                if niqqud_result.qc_flag:
                    qc_note = f"qc:{niqqud_result.qc_flag}"
                    notes_value = f"{notes_value}; {qc_note}".strip("; ").strip()
                entries.append(
                    {
                        "src_norm": src_norm,
                        "niqqud_text": niqqud_result.value,
                        "ipa": item.get("ipa"),
                        "reading_text": PronunciationQualityService.normalize_field(
                            item.get("reading_text"),
                            strict=False,
                        ).value,
                        "confidence": item.get("confidence"),
                        "notes": notes_value or None,
                    }
                )

            result = self.pronunciation_service.bulk_upsert_auto(
                session,
                lang=lang,
                entries=entries,
                chunk_size=chunk_size,
                rebuild_auto=rebuild_auto,
                source="auto_phonikud",
            )
            updated += int(result.get("updated", 0))
            skipped += int(result.get("skipped", 0))
            failed += int(result.get("failed", 0))

            processed = min(total, idx + len(chunk_norms))
            if progress_callback:
                progress_callback(processed, total)

        return PronunciationBootstrapResult(
            total_candidates=total,
            generated_candidates=generated_candidates,
            updated=updated,
            skipped=skipped,
            failed=failed,
            cancelled=cancelled,
            generator_mode=(getattr(self.generator, "mode", None) or "fallback"),
        )
