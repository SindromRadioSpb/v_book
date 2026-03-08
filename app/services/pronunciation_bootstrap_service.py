"""Offline bootstrap for pronunciation layer."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import asc, select
from sqlalchemy.orm import Session

from app.domain.normalization.normalizer import normalize_for_tm
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

    def health_check(
        self,
        sample_texts: Optional[List[str]] = None,
        *,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> PhonikudHealthReport:
        return self._adapter.health_check(sample_texts, cancel_check=cancel_check)

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

        def pick(
            norm_value: Optional[str],
            text_value: Optional[str],
            source_priority: int,
            row_id: int,
            *,
            item_lang: str,
        ) -> None:
            text = (text_value or "").strip()
            norm = normalize_for_tm(item_lang, text, "surface").norm
            norm = (norm or "").strip() or (norm_value or "").strip()
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
                    pick(norm_text, lemma_text, 0, int(lemma_id or 0), item_lang=lang)
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
                    pick(norm_text, representative_he, 1, int(cluster_id or 0), item_lang=lang)
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
                    pick(src_norm, src_text, 2, int(item_id or 0), item_lang=lang)
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

    def collect_selected_source_candidates(
        self,
        *,
        lang: str,
        selected_items: List[Dict[str, Any]],
        include_lemmas: bool = True,
        include_terms: bool = True,
        include_user_dictionary: bool = True,
        include_sentences: bool = False,
    ) -> Dict[str, str]:
        """Collect deterministic `(src_norm -> source_text)` map from selected rows."""
        selected: Dict[str, Tuple[Tuple[int, int, int, int, str], str]] = {}
        source_priority = {
            "lemmas": 0,
            "terms": 1,
            "user_dictionary": 2,
            "sentences": 3,
        }
        include_by_group = {
            "lemmas": bool(include_lemmas),
            "terms": bool(include_terms),
            "user_dictionary": bool(include_user_dictionary),
            "sentences": bool(include_sentences),
        }

        def _selected_pronunciation_norm(
            *,
            item_lang: str,
            text_value: str,
            group: str,
            provided_norm: Optional[str],
            provided_raw_norm: Optional[str],
        ) -> str:
            explicit = (provided_raw_norm or "").strip() or (provided_norm or "").strip()
            if group in {"lemmas", "terms"} and text_value:
                surface_norm = normalize_for_tm(item_lang, text_value, "surface").norm
                surface_norm = (surface_norm or "").strip()
                if surface_norm:
                    return surface_norm
            return explicit

        def pick(
            *,
            item_lang: str,
            norm_value: Optional[str],
            raw_norm_value: Optional[str],
            text_value: Optional[str],
            group: str,
            row_id: int,
        ) -> None:
            text = (text_value or "").strip()
            norm = _selected_pronunciation_norm(
                item_lang=item_lang,
                text_value=text,
                group=group,
                provided_norm=norm_value,
                provided_raw_norm=raw_norm_value,
            )
            if not norm or not text:
                return
            rank = self._candidate_rank(text, source_priority.get(group, 2), row_id)
            current = selected.get(norm)
            if current is None or rank < current[0]:
                selected[norm] = (rank, text)

        target_lang = (lang or "").strip().lower()
        for idx, raw in enumerate(selected_items or []):
            item_lang = (raw.get("src_lang") or lang).strip().lower()
            if item_lang and target_lang:
                same_family = item_lang.startswith("he") and target_lang.startswith("he")
                if item_lang != target_lang and not same_family:
                    continue
            elif item_lang and not target_lang:
                continue
            group = (raw.get("source_group") or "user_dictionary").strip().lower()
            if group not in include_by_group:
                group = "user_dictionary"
            if not include_by_group[group]:
                continue
            pick(
                item_lang=item_lang or target_lang or "he",
                norm_value=raw.get("src_norm"),
                raw_norm_value=raw.get("raw_src_norm"),
                text_value=raw.get("src_text"),
                group=group,
                row_id=idx,
            )

        return {src_norm: text for src_norm, (_rank, text) in selected.items()}

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
        include_sentences: bool = False,
        selected_items: Optional[List[Dict[str, Any]]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> PronunciationBootstrapResult:
        """Bootstrap pronunciation entries from available lexical norms."""
        source_candidates: Dict[str, str]
        if selected_items:
            source_candidates = self.collect_selected_source_candidates(
                lang=lang,
                selected_items=selected_items,
                include_lemmas=include_lemmas,
                include_terms=include_terms,
                include_user_dictionary=include_user_dictionary,
                include_sentences=include_sentences,
            )
        else:
            source_candidates = self.collect_source_candidates(
                session,
                lang=lang,
                include_lemmas=include_lemmas,
                include_terms=include_terms,
                include_user_dictionary=include_user_dictionary,
            )
        if not source_candidates:
            # Backward-compat fallback for slim fixture DBs and legacy tests.
            if selected_items:
                fallback_norms = sorted(
                    {
                        (raw.get("src_norm") or "").strip()
                        for raw in selected_items
                        if (raw.get("src_norm") or "").strip()
                    }
                )
                source_candidates = {norm: norm for norm in fallback_norms}
            else:
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
                niqqud_value = niqqud_result.value
                if PronunciationQualityService.has_source_structure_mismatch(source_text, niqqud_value):
                    source_sig = PronunciationQualityService.spoken_letters_signature(source_text)
                    candidate_sig = PronunciationQualityService.spoken_letters_signature(niqqud_value)
                    source_sig_compact = source_sig.replace(" ", "")
                    candidate_sig_compact = candidate_sig.replace(" ", "")
                    # When only spacing differs (common Phonikud separator artifacts like "ה|חומר"),
                    # keep generated nikud instead of falling back to plain source.
                    if source_sig_compact and candidate_sig_compact and source_sig_compact == candidate_sig_compact:
                        mismatch_note = "qc:source_spacing_variation"
                        notes_value = f"{notes_value}; {mismatch_note}".strip("; ").strip()
                    else:
                        fallback_source = PronunciationQualityService.sanitize_spoken_text(source_text)
                        if fallback_source:
                            niqqud_value = fallback_source
                            mismatch_note = "qc:source_structure_fallback"
                            notes_value = f"{notes_value}; {mismatch_note}".strip("; ").strip()
                        else:
                            failed += 1
                            continue
                if not PronunciationQualityService.has_hebrew_nikud(niqqud_value):
                    # Generator returned text unchanged (model unavailable or fallback mode).
                    # Writing source text as niqqud_text would pollute the column with
                    # unvowelled text, so skip this entry entirely.
                    skipped += 1
                    continue
                if niqqud_result.qc_flag:
                    qc_note = f"qc:{niqqud_result.qc_flag}"
                    notes_value = f"{notes_value}; {qc_note}".strip("; ").strip()
                entries.append(
                    {
                        "src_norm": src_norm,
                        "niqqud_text": niqqud_value,
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
